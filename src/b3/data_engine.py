import logging
from typing import Dict, Any, Tuple, List, Optional, Callable

from sqlalchemy.orm import Session

from src.b3.yahoo_connector import YahooConnector
from src.sources.base import SourceResult

logger = logging.getLogger("b3.engine")

# Faixas plausíveis: valores fora disso são descartados e geram aviso
# (ex.: o antigo bug do DY de 859% vindo do Yahoo).
FAIXAS_VALIDAS = {
    "PL": (-1000.0, 1000.0),
    "PVP": (-100.0, 100.0),
    "DY_pct": (0.0, 40.0),
    "ROE_pct": (-300.0, 300.0),
    "ROIC_pct": (-300.0, 300.0),
    "Margem_Liquida_pct": (-1000.0, 300.0),
    "Margem_Ebitda_pct": (-1000.0, 300.0),
    "EV_EBITDA": (-500.0, 500.0),
}
DIVERGENCIA_PRECO_MAX = 0.10  # 10%


class B3DataEngine:
    """
    Motor do Ecossistema B3: consulta todas as fontes ligadas (src/sources) e consolida.

    - Indicadores: a fonte de maior prioridade que trouxer cada indicador vence
      (ordem em src/sources/registry.py: Fundamentus > Yahoo > brapi).
    - Notícias: união deduplicada de Google News e feeds RSS.
    - Regulatório: documentos entregues à CVM. Macro: Banco Central.
    - Trava de Segurança: sem cotação/indicadores e sem notícias/documentos => "pausa_analise".
    """
    def __init__(self, collector: Optional[Callable[[Session, str], List[SourceResult]]] = None):
        self.yahoo = YahooConnector()
        if collector is None:
            from src.sources.registry import collect
            collector = collect
        self.collector = collector

    def get_asset_data(self, ticker: str, db: Optional[Session] = None) -> Tuple[Dict[str, Any], str]:
        """
        Retorna (dados_dict, status_coleta):
        "sucesso_primario" (tem cotação/indicadores), "sucesso_fallback" (só notícias/CVM) ou "pausa_analise".
        """
        normalized = self.yahoo.normalize_ticker(ticker)
        logger.info(f"[B3DataEngine] Coletando fontes para {normalized}")

        own_session = db is None
        if own_session:
            from src.database import SessionLocal
            db = SessionLocal()
        try:
            resultados = self.collector(db, normalized)
        finally:
            if own_session:
                db.close()

        return self.consolidate(normalized, resultados)

    @staticmethod
    def consolidate(ticker: str, resultados: List[SourceResult]) -> Tuple[Dict[str, Any], str]:
        ok = [r for r in resultados if r.ok]
        avisos: List[str] = []

        # --- Cotação, nome, setor e indicadores (por prioridade) ---
        nome = setor = None
        preco = None
        precos: Dict[str, float] = {}
        indicadores: Dict[str, Any] = {}
        indicadores_fontes: Dict[str, str] = {}
        for r in ok:
            if r.categoria not in ("fundamentos", "cotacao"):
                continue
            d = r.dados
            nome = nome or d.get("nome")
            setor = setor or d.get("setor")
            if d.get("preco_atual"):
                precos[r.fonte_nome] = float(d["preco_atual"])
                preco = preco if preco is not None else float(d["preco_atual"])
            for k, v in (d.get("indicadores") or {}).items():
                if v is None or k in indicadores:
                    continue
                faixa = FAIXAS_VALIDAS.get(k)
                if faixa and not (faixa[0] <= v <= faixa[1]):
                    msg = f"{k}={v} de {r.fonte_nome} descartado (fora da faixa plausível {faixa[0]}..{faixa[1]})"
                    avisos.append(msg)
                    r.avisos.append(msg)
                    continue
                indicadores[k] = v
                indicadores_fontes[k] = r.fonte_nome

        if len(precos) > 1:
            lo, hi = min(precos.values()), max(precos.values())
            if lo > 0 and (hi - lo) / lo > DIVERGENCIA_PRECO_MAX:
                avisos.append("Cotação diverge mais de 10% entre fontes: " +
                              ", ".join(f"{k} R$ {v:.2f}" for k, v in precos.items()))

        # --- Notícias (dedupe por título) ---
        noticias: List[Dict[str, Any]] = []
        vistos = set()
        for r in ok:
            if r.categoria != "noticias":
                continue
            for it in r.itens:
                chave = it["titulo"].strip().lower()[:80]
                if chave in vistos:
                    continue
                vistos.add(chave)
                noticias.append({**it, "via": r.fonte_nome})
        noticias.sort(key=lambda n: n.get("data") or "", reverse=True)
        noticias = noticias[:12]

        # --- CVM e Macro ---
        cvm: Dict[str, Any] = {}
        macro: Dict[str, Any] = {}
        for r in ok:
            if r.categoria == "regulatorio":
                cvm = {**r.dados, "documentos": r.itens}
            elif r.categoria == "macro":
                macro = dict(r.dados)

        fontes_ok = [r.fonte_nome for r in ok]
        fontes = [r.to_dict() for r in resultados]
        base = {
            "ticker": ticker,
            "nome": nome or ticker.replace(".SA", ""),
            "setor": setor or "B3",
            "preco_atual": preco or 0.0,
            "indicadores": indicadores,
            "indicadores_fontes": indicadores_fontes,
            "noticias": noticias,
            "cvm": cvm,
            "macro": macro,
            "fontes": fontes,
            "avisos": avisos,
            "fonte_utilizada": (", ".join(fontes_ok) or "NENHUMA")[:250],
        }

        if preco or indicadores:
            return {**base, "status_analise": "autorizado"}, "sucesso_primario"

        if noticias or cvm.get("documentos"):
            logger.warning(f"[B3DataEngine] {ticker}: sem cotação/indicadores; seguindo só com notícias/CVM.")
            return {**base, "status_analise": "autorizado"}, "sucesso_fallback"

        logger.error(f"[B3DataEngine] TRAVA DE SEGURANÇA ATIVADA para {ticker}: nenhuma fonte respondeu.")
        return {
            **base,
            "fonte_utilizada": "NENHUMA (Falha Total)",
            "status_analise": "pausa_analise",
            "motivo_bloqueio": "Bloqueio temporário de segurança por falta de confiabilidade nos dados (todas as fontes falharam)",
        }, "pausa_analise"

    def get_benchmark(self) -> Dict[str, Any]:
        """Obtém o benchmark Ibovespa"""
        return self.yahoo.fetch_ibovespa_trend()


_engine_instance = None

def get_b3_data_engine() -> B3DataEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = B3DataEngine()
    return _engine_instance
