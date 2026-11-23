from src.b3.yahoo_connector import YahooConnector
from src.b3.data_engine import B3DataEngine
from src.sources.base import SourceResult


def _res(fid, nome, cat, ok=True, **kw):
    return SourceResult(fonte_id=fid, fonte_nome=nome, categoria=cat, ok=ok, **kw)


def test_ticker_normalization():
    connector = YahooConnector()
    assert connector.normalize_ticker("petr4") == "PETR4.SA"
    assert connector.normalize_ticker("VALE3.SA") == "VALE3.SA"
    assert connector.normalize_ticker("^BVSP") == "^BVSP"


def test_trava_de_seguranca_pausa_analise():
    """Todas as fontes falham => pausa_analise"""
    falhas = [_res("yahoo", "Yahoo", "fundamentos", ok=False, erro="x"),
              _res("google_news", "Google News", "noticias", ok=False, erro="x")]
    engine = B3DataEngine(collector=lambda db, t: falhas)
    dados, status = engine.get_asset_data("UNKNOWN99", db=object())
    assert status == "pausa_analise"
    assert dados["status_analise"] == "pausa_analise"
    assert "Bloqueio temporário" in dados["motivo_bloqueio"]
    assert len(dados["fontes"]) == 2  # registra o que foi tentado, mesmo falhando


def test_dividend_yield_yahoo_formato_atual():
    # yfinance atual: dividendYield já em %, trailingAnnualDividendYield em fração
    assert round(YahooConnector.dividend_yield_pct({"dividendYield": 8.59, "trailingAnnualDividendYield": 0.0859}), 2) == 8.59
    assert YahooConnector.dividend_yield_pct({"dividendYield": 8.59}) == 8.59
    assert YahooConnector.dividend_yield_pct({}) == 0.0


def test_consolidacao_prioridade_validacao_e_noticias():
    resultados = [
        _res("fundamentus", "Fundamentus", "fundamentos",
             dados={"nome": "PETROBRAS PN", "setor": "Petróleo", "preco_atual": 42.0,
                    "indicadores": {"PL": 3.9, "DY_pct": 859.0}}),
        _res("yahoo", "Yahoo Finance", "fundamentos",
             dados={"preco_atual": 41.8, "indicadores": {"PL": 3.8, "DY_pct": 8.6, "ROE_pct": 30.0}}),
        _res("google_news", "Google News BR", "noticias",
             itens=[{"titulo": "Petrobras lucra", "link": "a", "data": "2026-11-20"},
                    {"titulo": "Outra", "link": "b", "data": "2026-11-21"}]),
        _res("moneytimes", "Money Times", "noticias",
             itens=[{"titulo": "PETROBRAS LUCRA", "link": "c", "data": "2026-11-20"}]),  # duplicada
        _res("cvm", "CVM", "regulatorio", dados={"empresa": "PETROBRAS", "qtd_fatos_relevantes_45d": 1},
             itens=[{"titulo": "[Fato Relevante] X", "link": "d", "data": "2026-11-10"}]),
        _res("bcb", "BCB", "macro", dados={"selic_meta_pct": 13.75}),
    ]
    dados, status = B3DataEngine.consolidate("PETR4.SA", resultados)

    assert status == "sucesso_primario"
    assert dados["preco_atual"] == 42.0                          # Fundamentus tem prioridade
    assert dados["indicadores"]["PL"] == 3.9
    assert dados["indicadores_fontes"]["PL"] == "Fundamentus"
    assert dados["indicadores"]["DY_pct"] == 8.6                 # 859% descartado, Yahoo assume
    assert dados["indicadores_fontes"]["DY_pct"] == "Yahoo Finance"
    assert dados["indicadores"]["ROE_pct"] == 30.0
    assert any("DY_pct=859.0" in a for a in dados["avisos"])
    assert len(dados["noticias"]) == 2                           # deduplicada
    assert dados["noticias"][0]["titulo"] == "Outra"             # mais recente primeiro
    assert dados["cvm"]["documentos"][0]["titulo"].startswith("[Fato Relevante]")
    assert dados["macro"]["selic_meta_pct"] == 13.75


def test_divergencia_de_preco_gera_aviso():
    resultados = [
        _res("fundamentus", "Fundamentus", "fundamentos", dados={"preco_atual": 10.0, "indicadores": {}}),
        _res("brapi", "brapi.dev", "cotacao", dados={"preco_atual": 13.0, "indicadores": {}}),
    ]
    dados, _ = B3DataEngine.consolidate("XPTO3.SA", resultados)
    assert any("diverge" in a for a in dados["avisos"])


def test_somente_noticias_vira_fallback():
    resultados = [_res("google_news", "Google News BR", "noticias", itens=[{"titulo": "x", "link": "", "data": None}])]
    _, status = B3DataEngine.consolidate("XPTO3.SA", resultados)
    assert status == "sucesso_fallback"
