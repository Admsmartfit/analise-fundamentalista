import logging
import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from src.models import TradeMemory, Asset, AuditLog
from src.llm.model_cascade import ModelCascadeManager, get_model_cascade

logger = logging.getLogger("memory.settle_reflect")

class SettleReflectEngine:
    """
    Motor de Memória de Aprendizado Contínuo (Inspirado em whitebirchio/trader).
    Recebe o resultado final das operações (WIN/LOSS) do robô técnico,
    conduz a análise Post-Mortem cruzando com a tese fundamentalista anterior
    e armazena a 'Lição Aprendida' para refinar futuros prompts.
    """
    def __init__(self, cascade: Optional[ModelCascadeManager] = None):
        self.cascade = cascade or get_model_cascade()

    def process_trade_feedback(
        self,
        db: Session,
        ticker: str,
        resultado: str,
        motivo_grafico: Optional[str] = None,
        lucro_prejuizo_pct: Optional[float] = None,
        detalhes: Optional[Dict[str, Any]] = None
    ) -> TradeMemory:
        """
        Processa o feedback do robô técnico, realiza a reflexão da IA
        e persiste a lição aprendida no banco de dados.
        """
        clean_ticker = ticker.upper().replace(".SA", "")
        symbol = f"{clean_ticker}.SA"

        # Localiza o ativo no banco para obter a tese prévia
        asset = db.query(Asset).filter((Asset.ticker == symbol) | (Asset.ticker == clean_ticker)).first()
        tese_anterior = asset.tese_resumida if asset else "Tese padrão não localizada no histórico."

        logger.info(f"[SettleReflect] Iniciando Reflexão Pós-Morte para {clean_ticker}: Resultado={resultado}, Motivo='{motivo_grafico}'")

        # Aciona o agente de reflexão via cascata de LLM
        licao = self.cascade.run_reflection(
            db=db,
            ticker=clean_ticker,
            resultado=resultado,
            motivo_grafico=motivo_grafico or "Fechamento técnico padrão",
            tese_original=tese_anterior
        )

        # Se o ativo não existe na base, cadastra com status pendente
        if not asset:
            asset = Asset(
                ticker=symbol,
                nome=clean_ticker,
                status_analise="pendente"
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)

        # Persiste o registro de memória
        memoria = TradeMemory(
            ticker=asset.ticker,
            resultado=resultado.upper().strip(),
            motivo_grafico=motivo_grafico,
            lucro_prejuizo_pct=lucro_prejuizo_pct,
            licao_aprendida=licao,
            tese_original=tese_anterior,
            created_at=datetime.datetime.utcnow()
        )
        db.add(memoria)

        # Log de auditoria
        log = AuditLog(
            level="INFO",
            category="ANALYSIS",
            message=f"Post-Mortem gerado para {clean_ticker} ({resultado}): {licao[:120]}...",
            details_json={"ticker": clean_ticker, "resultado": resultado, "motivo": motivo_grafico}
        )
        db.add(log)
        db.commit()
        db.refresh(memoria)

        logger.info(f"[SettleReflect] Lição Aprendida gravada com sucesso para {clean_ticker}: {licao}")
        return memoria

    def get_past_lessons(self, db: Session, ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Recupera histórico recente de lições aprendidas para injetar no prompt de análise"""
        clean_ticker = ticker.upper().replace(".SA", "")
        symbol = f"{clean_ticker}.SA"

        items = db.query(TradeMemory).filter(
            (TradeMemory.ticker == symbol) | (TradeMemory.ticker == clean_ticker)
        ).order_by(TradeMemory.created_at.desc()).limit(limit).all()

        return [
            {
                "resultado": item.resultado,
                "motivo_grafico": item.motivo_grafico,
                "licao_aprendida": item.licao_aprendida,
                "data": item.created_at.strftime("%Y-%m-%d %H:%M")
            }
            for item in items
        ]

_settle_instance = None

def get_settle_reflect_engine() -> SettleReflectEngine:
    global _settle_instance
    if _settle_instance is None:
        _settle_instance = SettleReflectEngine()
    return _settle_instance
