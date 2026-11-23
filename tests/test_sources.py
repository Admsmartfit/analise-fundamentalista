"""Testes offline das Fontes de Dados (sem rede)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.models import DataSourceConfig, AnalysisRun, User
from src.sources import registry
from src.sources.base import parse_br_number, DataSource, SourceResult
from src.sources.market import FundamentusSource
from src.sources.news import RSSSource, termos_empresa, parse_rss
from src.queue.worker import save_analysis_run, RUNS_POR_ATIVO
from src.llm.model_cascade import ModelCascadeManager, HEURISTICA


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _FakeResp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status
        self.text = content.decode("latin-1") if isinstance(content, bytes) else content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, content):
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        self.url = url
        return _FakeResp(self._content)


def test_parse_br_number():
    assert parse_br_number("1.234,56") == 1234.56
    assert parse_br_number("8,5%") == 8.5
    assert parse_br_number("-1,16%") == -1.16
    assert parse_br_number("-") is None
    assert parse_br_number("") is None


FUNDAMENTUS_HTML = """<html><body><table>
<tr><td class="label"><span>?</span>Cotação</td><td class="data">42,67</td></tr>
<tr><td class="label">?Empresa</td><td class="data">PETROBRAS PN</td></tr>
<tr><td class="label">?Setor</td><td class="data">Petróleo</td></tr>
<tr><td class="label">?P/L</td><td class="data">3,92</td></tr>
<tr><td class="label">?Div. Yield</td><td class="data">8,5%</td></tr>
<tr><td class="label">?ROE</td><td class="data">27,8%</td></tr>
<tr><td class="label">?Dív Líq / Patrim</td><td class="data">0,59</td></tr>
</table></body></html>""".encode("iso-8859-1")


def test_fundamentus_parse(monkeypatch):
    import src.sources.market as market
    monkeypatch.setattr(market.httpx, "Client", lambda **kw: _FakeClient(FUNDAMENTUS_HTML))
    r = FundamentusSource().fetch("PETR4.SA")
    assert r.ok, r.erro
    assert r.dados["preco_atual"] == 42.67
    assert r.dados["nome"] == "PETROBRAS PN"
    assert r.dados["indicadores"]["PL"] == 3.92
    assert r.dados["indicadores"]["DY_pct"] == 8.5
    assert r.dados["indicadores"]["Div_Liq_Patrimonio"] == 0.59


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Petrobras anuncia dividendos</title><link>http://a</link><pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Vale sobe na bolsa</title><link>http://b</link></item>
<item><title>PETR4 dispara</title><link>http://c</link></item>
</channel></rss>"""


def test_rss_feed_geral_filtra_pelo_ativo(monkeypatch):
    import src.sources.news as news
    monkeypatch.setattr(news.httpx, "Client", lambda **kw: _FakeClient(RSS))
    src = RSSSource("rss_x", "Feed X", "https://exemplo.com/feed/")
    r = src.fetch("PETR4.SA", {"nome": "PETROBRAS PN N2"})
    assert r.ok
    titulos = [i["titulo"] for i in r.itens]
    assert titulos == ["Petrobras anuncia dividendos", "PETR4 dispara"]
    assert r.itens[0]["data"] == "2026-11-23"


def test_rss_invalido_reporta_erro(monkeypatch):
    import src.sources.news as news
    monkeypatch.setattr(news.httpx, "Client", lambda **kw: _FakeClient(b"<html>nada</html>"))
    r = RSSSource("rss_x", "Feed X", "https://exemplo.com/{ticker}").fetch("PETR4")
    assert not r.ok
    assert "RSS" in r.erro


def test_termos_empresa():
    assert termos_empresa("PETR4.SA", {"nome": "PETROBRAS   PN      N2"}) == ["PETR4", "Petrobras"]
    assert termos_empresa("WEGE3", {"nome": "WEG ON NM"}) == ["WEGE3", "Weg"]
    assert termos_empresa("ITUB4", {}) == ["ITUB4"]


def test_fonte_que_lanca_excecao_nao_derruba_coleta():
    class Quebrada(DataSource):
        id, nome, categoria = "quebrada", "Quebrada", "fundamentos"

        def _fetch(self, ticker, result):
            raise ValueError("boom")

    r = Quebrada().fetch("PETR4")
    assert not r.ok and "boom" in r.erro and r.latencia_ms >= 0


def test_registry_configs_toggle_e_rss_customizado(db):
    configs = registry.ensure_configs(db)
    assert {"fundamentus", "yahoo", "cvm", "bcb", "google_news", "infomoney"} <= set(configs)

    cfg = registry.add_custom_rss(db, "Meu Blog", "https://blog.com/rss?q={ticker}")
    assert cfg.source_id == "rss_meu_blog"
    assert registry.add_custom_rss(db, "Meu Blog", "https://blog.com/feed").source_id == "rss_meu_blog_2"
    ids = [f.id for f in registry.build_sources(db)]
    assert "rss_meu_blog" in ids and ids.index("fundamentus") == 0

    # Coleta só as ligadas: desliga tudo menos uma fonte falsa
    for c in db.query(DataSourceConfig).all():
        c.enabled = False
    db.commit()
    assert registry.collect(db, "PETR4.SA") == []


def test_record_health(db):
    registry.ensure_configs(db)
    registry.record_health(db, SourceResult("yahoo", "Yahoo", "fundamentos", ok=False, erro="HTTP 500", latencia_ms=12))
    registry.record_health(db, SourceResult("yahoo", "Yahoo", "fundamentos", ok=True, resumo="R$ 1", latencia_ms=10))
    db.commit()
    c = db.query(DataSourceConfig).filter_by(source_id="yahoo").one()
    assert c.last_status == "ok" and c.last_error is None
    assert c.ok_count == 1 and c.fail_count == 1 and c.last_latency_ms == 10


def test_save_analysis_run_mantem_historico_limitado(db):
    for i in range(RUNS_POR_ATIVO + 3):
        save_analysis_run(db, "PETR4", {"fontes": [{"fonte_id": "yahoo"}], "avisos": []}, "sucesso_primario",
                          triagem_texto=f"t{i}", decisao_meta={"origem": "IA: gemini/x"})
        db.commit()
    runs = db.query(AnalysisRun).filter_by(ticker="PETR4").order_by(AnalysisRun.id.desc()).all()
    assert len(runs) == RUNS_POR_ATIVO
    assert runs[0].triagem_texto == f"t{RUNS_POR_ATIVO + 2}"
    assert runs[0].decisao_origem == "IA: gemini/x"


def test_cascade_sem_chave_informa_regra_de_contingencia(db):
    meta = {}
    veredito = ModelCascadeManager().run_manager_verdict(
        db, "PETR4", {"indicadores": {"ROE_pct": 20, "PL": 5}}, "neutro", [], meta=meta)
    assert meta["origem"] == HEURISTICA
    assert "chave" in meta["erro"]
    assert veredito["status"] in ("autorizado", "rejeitado")


def test_api_fontes_endpoints(db, monkeypatch):
    from src.web import api_routes
    from src.schemas import CustomRSSCreate, SourceToggleRequest
    user = User(username="t", hashed_password="x")

    lista = api_routes.list_sources(db, user)
    assert any(f["id"] == "cvm" and f["categoria"] == "regulatorio" for f in lista)

    api_routes.toggle_source("brapi", SourceToggleRequest(enabled=False), db, user)
    assert not db.query(DataSourceConfig).filter_by(source_id="brapi").one().enabled

    res = api_routes.add_custom_source(CustomRSSCreate(nome="Teste", url_template="https://x.com/rss"), db, user)
    assert res["source_id"] == "rss_teste"
    api_routes.delete_custom_source("rss_teste", db, user)
    with pytest.raises(Exception):
        api_routes.delete_custom_source("yahoo", db, user)  # embutida não pode ser removida


def test_gemini_troca_de_modelo_quando_sobrecarregado(monkeypatch):
    import httpx as _httpx
    import src.llm.model_cascade as mc
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    chamadas = []

    class _Resp:
        def __init__(self, code, body=None):
            self.status_code, self._body, self.text = code, body or {}, "x"
        def json(self):
            return self._body
        def raise_for_status(self):
            if self.status_code >= 400:
                raise _httpx.HTTPStatusError("e", request=None, response=self)

    def fake_post(self, url, **kw):
        chamadas.append(url)
        if mc.GEMINI_MODEL in url:
            return _Resp(503)
        return _Resp(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

    monkeypatch.setattr(_httpx.Client, "post", fake_post)
    cascade = ModelCascadeManager(key_pool=object())
    assert cascade._call_llm_api("gemini", "k", "oi") == "OK"
    assert len(chamadas) == 3                      # 2 tentativas no principal + 1 no reserva
    assert cascade._origem("gemini") == f"IA: gemini/{mc.GEMINI_FALLBACK_MODELS[0]}"
