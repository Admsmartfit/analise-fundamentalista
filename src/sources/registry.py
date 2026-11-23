"""
Registro central das Fontes de Dados.

Para incluir uma fonte nova em código: crie a subclasse de `DataSource` e
acrescente-a em `FONTES_EMBUTIDAS`. A ordem da lista é a prioridade na hora de
consolidar indicadores (a primeira fonte que trouxer um indicador vence).
Feeds RSS podem ser cadastrados direto pela tela, sem código.
"""
import re
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from src.models import DataSourceConfig, SystemSetting
from src.sources.base import DataSource, SourceResult
from src.sources.market import FundamentusSource, YahooSource, BrapiSource
from src.sources.news import GoogleNewsSource, RSSSource, RSS_EMBUTIDOS
from src.sources.official import CVMSource, BCBMacroSource

logger = logging.getLogger("sources.registry")

FONTES_EMBUTIDAS = [FundamentusSource, YahooSource, BrapiSource, CVMSource, BCBMacroSource, GoogleNewsSource]

# Fontes desligadas por padrão na primeira execução
DESLIGADAS_POR_PADRAO: set = set()


def _settings(db: Session) -> Dict[str, str]:
    return {s.key: s.value or "" for s in db.query(SystemSetting).all()}


def ensure_configs(db: Session) -> Dict[str, DataSourceConfig]:
    """Garante uma linha de configuração para cada fonte embutida."""
    configs = {c.source_id: c for c in db.query(DataSourceConfig).all()}
    ids = [cls.id for cls in FONTES_EMBUTIDAS] + [r[0] for r in RSS_EMBUTIDOS]
    novos = False
    for sid in ids:
        if sid not in configs:
            c = DataSourceConfig(source_id=sid, enabled=sid not in DESLIGADAS_POR_PADRAO)
            db.add(c)
            configs[sid] = c
            novos = True
    if novos:
        db.commit()
    return configs


def build_sources(db: Session) -> List[DataSource]:
    """Instancia todas as fontes (ligadas e desligadas), na ordem de prioridade."""
    settings = _settings(db)
    configs = ensure_configs(db)
    fontes: List[DataSource] = [cls(settings) for cls in FONTES_EMBUTIDAS]
    fontes += [RSSSource(sid, nome, url, desc, removivel=False, settings=settings)
               for sid, nome, url, desc in RSS_EMBUTIDOS]
    for c in sorted(configs.values(), key=lambda c: c.id):
        if c.is_custom and c.url_template:
            fontes.append(RSSSource(c.source_id, c.nome or c.source_id, c.url_template, settings=settings))
    return fontes


def is_enabled(db: Session, source_id: str) -> bool:
    c = db.query(DataSourceConfig).filter(DataSourceConfig.source_id == source_id).first()
    return bool(c and c.enabled)


def record_health(db: Session, result: SourceResult) -> None:
    c = db.query(DataSourceConfig).filter(DataSourceConfig.source_id == result.fonte_id).first()
    if not c:
        return
    now = datetime.datetime.utcnow()
    c.last_checked_at = now
    c.last_latency_ms = result.latencia_ms
    c.last_resumo = result.resumo
    if result.ok:
        c.last_status = "ok"
        c.last_ok_at = now
        c.last_error = None
        c.ok_count = (c.ok_count or 0) + 1
    else:
        c.last_status = "erro"
        c.last_error = result.erro
        c.fail_count = (c.fail_count or 0) + 1


def _contexto(resultados: List[SourceResult]) -> Dict[str, str]:
    """Nome da empresa descoberto pelas fontes de fundamentos, para as fontes de notícias."""
    for r in resultados:
        if r.ok and r.dados.get("nome"):
            return {"nome": r.dados["nome"]}
    return {}


def collect(db: Session, ticker: str, only: Optional[List[str]] = None) -> List[SourceResult]:
    """
    Consulta em paralelo todas as fontes ligadas (ou só as de `only`).
    Fase 1: fundamentos/cotação/CVM/macro. Fase 2: notícias (usam o nome da empresa da fase 1).
    Atualiza a saúde de cada fonte no banco.
    """
    configs = ensure_configs(db)
    fontes = [f for f in build_sources(db)
              if (only is not None and f.id in only)
              or (only is None and configs.get(f.id) and configs[f.id].enabled)]

    fase1 = [f for f in fontes if f.categoria != "noticias"]
    fase2 = [f for f in fontes if f.categoria == "noticias"]
    resultados: List[SourceResult] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados += list(pool.map(lambda f: f.fetch(ticker), fase1))
        ctx = _contexto(resultados)
        resultados += list(pool.map(lambda f: f.fetch(ticker, ctx), fase2))

    for r in resultados:
        record_health(db, r)
    db.commit()
    return resultados


def test_source(db: Session, source_id: str, ticker: str) -> Optional[SourceResult]:
    """Executa uma única fonte (mesmo desligada) para o botão "Testar"."""
    fonte = next((f for f in build_sources(db) if f.id == source_id), None)
    if not fonte:
        return None
    ctx = {}
    if fonte.categoria == "noticias":
        # Descobre o nome da empresa para o filtro, como na coleta real
        for f in build_sources(db):
            if f.id in ("fundamentus", "yahoo") and is_enabled(db, f.id):
                r = f.fetch(ticker)
                if r.ok:
                    ctx = {"nome": r.dados.get("nome")}
                    break
    result = fonte.fetch(ticker, ctx)
    record_health(db, result)
    db.commit()
    return result


def add_custom_rss(db: Session, nome: str, url_template: str) -> DataSourceConfig:
    base = re.sub(r"[^a-z0-9]+", "_", nome.lower()).strip("_")[:30] or "rss"
    sid = f"rss_{base}"
    n = 2
    while db.query(DataSourceConfig).filter(DataSourceConfig.source_id == sid).first():
        sid = f"rss_{base}_{n}"
        n += 1
    c = DataSourceConfig(source_id=sid, enabled=True, is_custom=True, nome=nome.strip(),
                         url_template=url_template.strip())
    db.add(c)
    db.commit()
    db.refresh(c)
    return c
