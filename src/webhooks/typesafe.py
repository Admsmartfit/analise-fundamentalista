import datetime
from typing import Dict, Any, Optional
from src.schemas import DecisionCallbackPayload

class TypeSafeDecisionFormatter:
    """
    Formatador TypeSafe e Tipagem Rígida (Inspirado em TradingAgents-Jev).
    Garante que a saída emitida para o Robô Técnico seja um JSON estrito,
    eliminando ambiguidades de texto livre.
    """

    @staticmethod
    def format_decision(
        ticker: str,
        status: str,
        conviccao: float,
        validade_dias: int,
        tese_resumida: str,
        indicadores: Optional[Dict[str, Any]] = None,
        id_analise: Optional[int] = None,
        origem_decisao: Optional[str] = None,
        fontes_consultadas: Optional[str] = None
    ) -> DecisionCallbackPayload:
        """Gera payload validado estritamente por Pydantic"""
        clean_ticker = ticker.upper().replace(".SA", "")
        now = datetime.datetime.utcnow()
        expiracao = now + datetime.timedelta(days=validade_dias)

        valid_status = status.lower().strip()
        if valid_status not in ("autorizado", "rejeitado", "pausa_analise"):
            valid_status = "rejeitado"

        bounded_conviccao = max(0.0, min(1.0, float(conviccao)))

        return DecisionCallbackPayload(
            ativo=clean_ticker,
            status=valid_status,
            conviccao=round(bounded_conviccao, 2),
            validade_dias=int(validade_dias),
            tese_resumida=tese_resumida.strip(),
            indicadores_chave=indicadores or {},
            data_autorizacao=now,
            data_expiracao=expiracao,
            timestamp=now,
            id_analise=id_analise,
            origem_decisao=origem_decisao,
            fontes_consultadas=fontes_consultadas
        )
