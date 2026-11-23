import logging
from typing import Optional
import httpx
from src.config import (
    EVOLUTION_API_URL, EVOLUTION_API_KEY,
    EVOLUTION_INSTANCE, EVOLUTION_RECIPIENT_NUMBER
)

logger = logging.getLogger("notifications.evolution")

class EvolutionApiClient:
    """
    Cliente de Notificações WhatsApp via Evolution API.
    Atenção: Disparado ESTRITAMENTE para os 3 eventos sistêmicos restritos:
    1. Esgotamento total do Key Pool (Zero chaves disponíveis)
    2. Eventos de Watchdog (Nova versão no upstream ou update agendado às 03:00 AM)
    3. Alerta de infraestrutura (Queda consecutiva severa de Webhooks do Robô Técnico)
    Zero spam para análises normais de ativos.
    """
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        instance: Optional[str] = None,
        recipient: Optional[str] = None
    ):
        self.api_url = (api_url or EVOLUTION_API_URL).rstrip("/")
        self.api_key = api_key or EVOLUTION_API_KEY
        self.instance = instance or EVOLUTION_INSTANCE
        self.recipient = recipient or EVOLUTION_RECIPIENT_NUMBER

    def send_restricted_alert(self, titulo: str, mensagem: str, categoria: str) -> bool:
        """
        Dispara mensagem de texto formatada para o número configurado.
        Valida que a categoria pertença aos 3 eventos permitidos.
        """
        permitidas = ("KEY_POOL_EXHAUSTED", "WATCHDOG_ALERT", "INFRASTRUCTURE_FAILURE")
        if categoria not in permitidas:
            logger.warning(f"[EvolutionAPI] Bloqueio anti-spam ativado: Categoria '{categoria}' não é um dos 3 eventos restritos.")
            return False

        if not self.api_url or not self.api_key or not self.recipient:
            logger.info(f"[EvolutionAPI Simulado] {titulo}: {mensagem} (Evolution API não configurada no .env)")
            return True

        endpoint = f"{self.api_url}/message/sendText/{self.instance}"
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
        texto_completo = f"🚨 *[TRADINGAGENTS B3 - {titulo}]*\n\n{mensagem}\n\n_Horário: UTC_"

        payload = {
            "number": self.recipient,
            "text": texto_completo,
            "options": {
                "delay": 1200,
                "presence": "composing"
            }
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(endpoint, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    logger.info(f"[EvolutionAPI] Alerta restrito enviado com sucesso via WhatsApp ({categoria})")
                    return True
                else:
                    logger.error(f"[EvolutionAPI] Falha ao enviar WhatsApp ({resp.status_code}): {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"[EvolutionAPI] Exceção de rede ao conectar com Evolution API: {e}")
            return False

_evolution_client = None

def get_evolution_client() -> EvolutionApiClient:
    global _evolution_client
    if _evolution_client is None:
        _evolution_client = EvolutionApiClient()
    return _evolution_client
