import logging
import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from src.models import QueueItem, AuditLog
from src.schemas import QueueDemandResponse

logger = logging.getLogger("queue.smart_queue")

class SmartQueueManager:
    """
    Gestão Assíncrona de Demanda (Smart Queue).
    Recebe listas de ativos do Robô Técnico ou do Cockpit Web e responde
    imediatamente em milissegundos com HTTP 200, liberando o solicitante
    enquanto processa os papéis em segundo plano em lotes controlados.
    """
    def __init__(self):
        pass

    def enqueue_assets(
        self,
        db: Session,
        ativos: List[str],
        prioridade: str = "normal",
        origem: str = "robo_tecnico"
    ) -> QueueDemandResponse:
        """
        Enfileira os ativos fornecidos e retorna confirmação imediata.
        Evita duplicações ativas se o papel já estiver na fila aguardando.
        """
        enqueued_tickers = []
        now = datetime.datetime.utcnow()

        for raw_ticker in ativos:
            ticker = raw_ticker.strip().upper().replace(".SA", "")
            symbol = f"{ticker}.SA"

            # Checa se já existe na fila como 'queued' ou 'processing'
            existing = db.query(QueueItem).filter(
                QueueItem.ticker == symbol,
                QueueItem.status.in_(["queued", "processing"])
            ).first()

            if existing:
                # Atualiza prioridade se a nova for maior
                if prioridade in ("alta", "urgente"):
                    existing.prioridade = prioridade
                    db.commit()
                enqueued_tickers.append(ticker)
                continue

            item = QueueItem(
                ticker=symbol,
                prioridade=prioridade,
                status="queued",
                request_source=origem,
                queued_at=now
            )
            db.add(item)
            enqueued_tickers.append(ticker)

        log = AuditLog(
            level="INFO",
            category="QUEUE",
            message=f"{len(enqueued_tickers)} ativos recebidos na Smart Queue via {origem} (Prioridade: {prioridade}).",
            details_json={"ativos": enqueued_tickers, "origem": origem}
        )
        db.add(log)
        db.commit()

        logger.info(f"[SmartQueue] {len(enqueued_tickers)} ativos enfileirados com sucesso.")

        return QueueDemandResponse(
            status="queued",
            message="Ativos na Fila",
            ativos=enqueued_tickers,
            total_enfileirados=len(enqueued_tickers),
            timestamp=now
        )

    def get_queue_status(self, db: Session) -> Dict[str, Any]:
        """Retorna resumo métrico do estado da fila ao vivo"""
        queued_count = db.query(QueueItem).filter(QueueItem.status == "queued").count()
        processing_count = db.query(QueueItem).filter(QueueItem.status == "processing").count()
        completed_today = db.query(QueueItem).filter(
            QueueItem.status == "completed",
            QueueItem.completed_at >= datetime.datetime.utcnow().date()
        ).count()

        return {
            "aguardando": queued_count,
            "em_processamento": processing_count,
            "concluidos_hoje": completed_today,
            "total_ativo": queued_count + processing_count
        }

_queue_manager_instance = None

def get_smart_queue() -> SmartQueueManager:
    global _queue_manager_instance
    if _queue_manager_instance is None:
        _queue_manager_instance = SmartQueueManager()
    return _queue_manager_instance
