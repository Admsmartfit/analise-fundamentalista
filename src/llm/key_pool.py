import logging
import datetime
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from src.models import ApiKey, AuditLog

logger = logging.getLogger("llm.key_pool")

class KeyPoolManager:
    """
    Gerenciador de Pool de Chaves com Hot-Swap Automático.
    Monitora limites de taxa (Rate Limit) e cotas de uso para múltiplos provedores:
    Gemini, Claude, DeepSeek, OpenAI e Groq.
    """
    def __init__(self):
        pass

    def get_available_key(self, db: Session, provider: Optional[str] = None) -> Optional[ApiKey]:
        """
        Retorna a melhor chave ativa disponível para o provedor solicitado (ou qualquer ativo).
        Prioriza por prioridade ascendente (1 > 2) e menor uso acumulado.
        """
        query = db.query(ApiKey).filter(
            ApiKey.is_active == True,
            ApiKey.rate_limit_hit == False
        )
        if provider:
            query = query.filter(ApiKey.provider == provider.lower())

        # Reset automático de rate limit se passou mais de 1 hora
        now = datetime.datetime.utcnow()
        rate_limited_keys = db.query(ApiKey).filter(
            ApiKey.rate_limit_hit == True,
            ApiKey.rate_limit_reset_at <= now
        ).all()
        for k in rate_limited_keys:
            k.rate_limit_hit = False
            k.rate_limit_reset_at = None
        if rate_limited_keys:
            db.commit()

        key = query.order_by(ApiKey.priority.asc(), ApiKey.current_usage.asc()).first()
        return key

    def record_usage(self, db: Session, key_id: int, tokens_or_calls: int = 1):
        """Registra consumo de uso na chave"""
        key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        if key:
            key.current_usage += tokens_or_calls
            key.last_used_at = datetime.datetime.utcnow()
            if key.daily_limit and key.current_usage >= key.daily_limit:
                logger.warning(f"[KeyPool] Chave {key.label} ({key.provider}) atingiu a cota diária ({key.current_usage}/{key.daily_limit}).")
                key.rate_limit_hit = True
                key.rate_limit_reset_at = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
            db.commit()

    def mark_rate_limited(self, db: Session, key_id: int, retry_after_minutes: int = 15) -> bool:
        """
        Marca chave como esgotada por Rate Limit e aciona Hot-Swap para a próxima.
        Retorna True se ainda houver outras chaves ativas no pool, ou False se o pool esgotou.
        """
        key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
        if not key:
            return False

        key.rate_limit_hit = True
        key.rate_limit_reset_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=retry_after_minutes)
        db.commit()

        logger.warning(f"[KeyPool Hot-Swap] Chave ID {key_id} ({key.provider}) marcada com Rate Limit. Buscando substituta...")

        # Verifica se ainda restam chaves ativas
        has_remaining = db.query(ApiKey).filter(
            ApiKey.is_active == True,
            ApiKey.rate_limit_hit == False
        ).first() is not None

        if not has_remaining:
            logger.critical("[KeyPool] ESGOTAMENTO TOTAL DO KEY POOL: Nenhuma chave disponível!")
            # Registra no log de auditoria
            log = AuditLog(
                level="CRITICAL",
                category="KEY_POOL",
                message="Esgotamento total do Key Pool. Todas as chaves atingiram o limite ou cota.",
                details_json={"provider": key.provider, "key_id": key_id}
            )
            db.add(log)
            db.commit()

        return has_remaining

    def is_pool_exhausted(self, db: Session) -> bool:
        """Verifica se todas as chaves cadastradas estão inativas ou atingiram o rate limit"""
        total = db.query(ApiKey).count()
        if total == 0:
            return True
        available = db.query(ApiKey).filter(
            ApiKey.is_active == True,
            ApiKey.rate_limit_hit == False
        ).count()
        return available == 0

    def add_key(self, db: Session, provider: str, key_value: str, label: Optional[str] = None, daily_limit: int = 1000, priority: int = 1) -> ApiKey:
        """Cadastra nova chave no pool"""
        new_key = ApiKey(
            provider=provider.lower().strip(),
            label=label or f"{provider.capitalize()} Key",
            key_value=key_value.strip(),
            daily_limit=daily_limit,
            priority=priority,
            is_active=True,
            rate_limit_hit=False
        )
        db.add(new_key)
        db.commit()
        db.refresh(new_key)
        return new_key

_key_pool_instance = None

def get_key_pool_manager() -> KeyPoolManager:
    global _key_pool_instance
    if _key_pool_instance is None:
        _key_pool_instance = KeyPoolManager()
    return _key_pool_instance
