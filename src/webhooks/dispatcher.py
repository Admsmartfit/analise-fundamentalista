import logging
import datetime
import httpx
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from src.models import WebhookOutbox, AuditLog, SystemSetting
from src.config import TECHNICAL_ROBOT_WEBHOOK_URL, WEBHOOK_MAX_RETRIES, WEBHOOK_TIMEOUT_SECONDS, WEBHOOK_RETRY_INTERVALS
from src.schemas import DecisionCallbackPayload

logger = logging.getLogger("webhooks.dispatcher")

class WebhookDispatcher:
    """
    Despachante de Webhooks com Fila de Retentativa Exponencial (Outbox Pattern).
    Dispara decisões para o Robô Técnico e gerencia alertas de infraestrutura
    em caso de falhas consecutivas.
    """
    def __init__(self, target_url: Optional[str] = None):
        self.target_url = target_url or TECHNICAL_ROBOT_WEBHOOK_URL

    def resolve_target_url(self, db: Session) -> str:
        """URL configurada no Cockpit (Watchdog & Ajustes) tem precedência sobre o .env."""
        setting = db.query(SystemSetting).filter(SystemSetting.key == "technical_robot_webhook_url").first()
        if setting and setting.value and setting.value.strip():
            return setting.value.strip()
        return self.target_url

    def queue_decision(self, db: Session, decision: DecisionCallbackPayload, target_url: Optional[str] = None) -> WebhookOutbox:
        """Adiciona decisão na fila outbox para envio imediato e retentativas"""
        url = target_url or self.resolve_target_url(db)
        outbox_entry = WebhookOutbox(
            target_url=url,
            payload_json=decision.model_dump(mode="json"),
            status="pending",
            retry_count=0,
            next_retry_at=datetime.datetime.utcnow(),
            created_at=datetime.datetime.utcnow()
        )
        db.add(outbox_entry)
        db.commit()
        db.refresh(outbox_entry)

        # Tenta envio síncrono imediato
        self.attempt_delivery(db, outbox_entry.id)
        return outbox_entry

    def attempt_delivery(self, db: Session, outbox_id: int) -> bool:
        """Tenta enviar a mensagem para o endpoint externo"""
        entry = db.query(WebhookOutbox).filter(WebhookOutbox.id == outbox_id).first()
        if not entry or entry.status == "delivered":
            return True

        try:
            with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
                resp = client.post(entry.target_url, json=entry.payload_json)
                if resp.status_code in (200, 201, 202, 204):
                    entry.status = "delivered"
                    entry.delivered_at = datetime.datetime.utcnow()
                    entry.last_error = None
                    db.commit()
                    logger.info(f"[WebhookDispatcher] Sucesso no envio do webhook ID {entry.id} para {entry.target_url}")
                    return True
                else:
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    return self._handle_delivery_failure(db, entry, error_msg)
        except Exception as e:
            return self._handle_delivery_failure(db, entry, str(e))

    def _handle_delivery_failure(self, db: Session, entry: WebhookOutbox, error_msg: str) -> bool:
        """Gerencia falha e agenda próxima retentativa com backoff exponencial"""
        entry.retry_count += 1
        entry.last_error = error_msg
        now = datetime.datetime.utcnow()

        if entry.retry_count >= WEBHOOK_MAX_RETRIES:
            entry.status = "failed"
            logger.error(f"[WebhookDispatcher] Webhook ID {entry.id} atingiu limite máximo de {WEBHOOK_MAX_RETRIES} retentativas. Falhou definitivamente.")
            
            # Registra no log de auditoria
            log = AuditLog(
                level="ERROR",
                category="WEBHOOK",
                message=f"Falha definitiva ao entregar webhook para {entry.target_url}: {error_msg}",
                details_json={"outbox_id": entry.id, "retries": entry.retry_count}
            )
            db.add(log)
            db.commit()

            # Checa se há falhas consecutivas graves para alerta de infraestrutura
            self._check_infrastructure_health(db)
            return False

        # Calcula próximo intervalo da lista
        interval_idx = min(entry.retry_count - 1, len(WEBHOOK_RETRY_INTERVALS) - 1)
        delay_seconds = WEBHOOK_RETRY_INTERVALS[interval_idx]
        entry.next_retry_at = now + datetime.timedelta(seconds=delay_seconds)
        db.commit()

        logger.warning(
            f"[WebhookDispatcher] Falha ao enviar Webhook ID {entry.id} ({error_msg}). "
            f"Retentativa {entry.retry_count}/{WEBHOOK_MAX_RETRIES} agendada em {delay_seconds}s."
        )
        return False

    def process_pending_retries(self, db: Session):
        """Varre o banco e tenta reenviar mensagens pendentes cuja hora de retentativa já chegou"""
        now = datetime.datetime.utcnow()
        pending = db.query(WebhookOutbox).filter(
            WebhookOutbox.status == "pending",
            WebhookOutbox.next_retry_at <= now
        ).all()

        for item in pending:
            self.attempt_delivery(db, item.id)

    def force_retry_all(self, db: Session) -> int:
        """
        Botão "Forçar Retentativas": reenvia agora tudo que não foi entregue (pendentes e falhas
        definitivas), usando a URL atual do Cockpit — útil depois de corrigir a URL ou religar o robô.
        """
        url = self.resolve_target_url(db)
        entries = db.query(WebhookOutbox).filter(WebhookOutbox.status.in_(["pending", "failed"])).all()
        for e in entries:
            e.status = "pending"
            e.retry_count = 0
            e.target_url = url
            e.next_retry_at = datetime.datetime.utcnow()
        db.commit()
        for e in entries:
            self.attempt_delivery(db, e.id)
        return len(entries)

    def _check_infrastructure_health(self, db: Session):
        """Detecta queda consecutiva severa da comunicação com o robô técnico"""
        recent_failed = db.query(WebhookOutbox).filter(
            WebhookOutbox.status == "failed"
        ).order_by(WebhookOutbox.id.desc()).limit(3).all()

        if len(recent_failed) >= 3:
            logger.critical("[WebhookDispatcher] ALERTA DE INFRAESTRUTURA: Queda severa na comunicação com o Robô Técnico (>=3 falhas consecutivas)!")
            log = AuditLog(
                level="CRITICAL",
                category="INFRASTRUCTURE",
                message="Queda severa na comunicação com o Robô Técnico. Múltiplos webhooks falharam consecutivamente.",
                details_json={"failed_count": len(recent_failed)}
            )
            db.add(log)
            db.commit()

_dispatcher_instance = None

def get_webhook_dispatcher() -> WebhookDispatcher:
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = WebhookDispatcher()
    return _dispatcher_instance
