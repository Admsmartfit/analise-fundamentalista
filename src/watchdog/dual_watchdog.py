import logging
import datetime
import subprocess
from typing import Optional, Dict, Any
import httpx
from sqlalchemy.orm import Session
from src.models import WatchdogState, AuditLog
from src.config import UPSTREAM_REPO, CUSTOM_REPO, AUTO_UPDATE_HOUR, AUTO_UPDATE_MINUTE, UPSTREAM_DIR
from src.notifications.evolution_api import EvolutionApiClient, get_evolution_client

logger = logging.getLogger("watchdog.dual")

class DualWatchdogManager:
    """
    Watchdog Duplo (Atualização Segura):
    1. Watchdog Upstream (TauricResearch/TradingAgents):
       - Detecta novidades no repositório original
       - Exibe aviso visual no Cockpit Web
       - Dispara notificação WhatsApp
       - Atualização estritamente MANUAL (não altera upstream automaticamente)
    2. Watchdog Customizado:
       - Monitora commits no repositório customizado
       - Exibe aviso visual no Cockpit
       - Agenda auto-update e restart para as 03:00 AM (fora do horário de pregão)
    """
    def __init__(self, evolution_client: Optional[EvolutionApiClient] = None):
        self.evolution = evolution_client or get_evolution_client()

    def check_upstream(self, db: Session) -> Dict[str, Any]:
        """Verifica novidades no repositório oficial do TauricResearch/TradingAgents"""
        state = db.query(WatchdogState).filter(WatchdogState.target == "upstream").first()
        if not state:
            state = WatchdogState(
                target="upstream",
                current_commit=self._get_local_upstream_commit(),
                update_available=False
            )
            db.add(state)
            db.commit()
            db.refresh(state)

        # Checa commit mais recente na API do GitHub
        remote_sha = self._fetch_github_latest_sha(UPSTREAM_REPO)
        state.last_checked_at = datetime.datetime.utcnow()

        # Sem clone local (ex.: versão instalada) não há commit de referência: o primeiro commit remoto
        # visto vira a referência, sem alarme. Antes, um valor fictício gerava alerta falso permanente.
        if remote_sha and state.current_commit in (None, "", "upstream-init-sha"):
            state.current_commit = remote_sha
            state.remote_commit = remote_sha
            state.update_available = False

        if remote_sha and state.current_commit and remote_sha != state.current_commit:
            if not state.update_available:
                state.update_available = True
                state.remote_commit = remote_sha
                logger.warning(f"[Watchdog Upstream] Nova versão detectada no repositório oficial: {remote_sha[:7]}")
                
                # Alerta no banco
                log = AuditLog(
                    level="WARNING",
                    category="WATCHDOG",
                    message=f"Nova versão oficial detectada no repositório {UPSTREAM_REPO} ({remote_sha[:7]}). Atualização manual necessária.",
                    details_json={"upstream_repo": UPSTREAM_REPO, "remote_commit": remote_sha}
                )
                db.add(log)
                db.commit()

                # Notificação restrita no WhatsApp
                self.evolution.send_restricted_alert(
                    titulo="NOVA VERSÃO OFICIAL DETECTADA",
                    mensagem=f"O repositório base *{UPSTREAM_REPO}* recebeu atualizações ({remote_sha[:7]}). O sistema continua operando normalmente. Acesse o Cockpit para revisão manual.",
                    categoria="WATCHDOG_ALERT"
                )
        elif remote_sha:
            state.remote_commit = remote_sha

        db.commit()
        return {
            "target": "upstream",
            "current_commit": state.current_commit,
            "remote_commit": state.remote_commit,
            "update_available": state.update_available,
            "last_checked_at": state.last_checked_at
        }

    def check_custom_repo(self, db: Session) -> Dict[str, Any]:
        """
        Verifica commits na sua camada customizada B3.
        Se houver atualização, agenda auto-update para as 03:00 AM.
        """
        state = db.query(WatchdogState).filter(WatchdogState.target == "custom").first()
        if not state:
            state = WatchdogState(
                target="custom",
                current_commit=self._get_local_git_commit(),
                update_available=False
            )
            db.add(state)
            db.commit()
            db.refresh(state)

        if not CUSTOM_REPO:
            # Sem repositório remoto customizado configurado
            return {
                "target": "custom",
                "current_commit": state.current_commit,
                "remote_commit": state.current_commit,
                "update_available": False,
                "scheduled_update_at": state.scheduled_update_at
            }

        remote_sha = self._fetch_github_latest_sha(CUSTOM_REPO)
        state.last_checked_at = datetime.datetime.utcnow()

        if remote_sha and state.current_commit and remote_sha != state.current_commit:
            if not state.update_available:
                state.update_available = True
                state.remote_commit = remote_sha

                # Agenda atualização para as 03:00 AM do dia seguinte
                now = datetime.datetime.utcnow()
                scheduled_time = now.replace(hour=AUTO_UPDATE_HOUR, minute=AUTO_UPDATE_MINUTE, second=0, microsecond=0)
                if scheduled_time <= now:
                    scheduled_time += datetime.timedelta(days=1)
                state.scheduled_update_at = scheduled_time

                log = AuditLog(
                    level="INFO",
                    category="WATCHDOG",
                    message=f"Atualização customizada detectada ({remote_sha[:7]}). Instalação agendada para {scheduled_time.strftime('%d/%m às %H:%M UTC')}.",
                    details_json={"custom_repo": CUSTOM_REPO, "scheduled_at": scheduled_time.isoformat()}
                )
                db.add(log)
                db.commit()

                # Notificação restrita no WhatsApp
                self.evolution.send_restricted_alert(
                    titulo="AUTO-UPDATE AGENDADO (03:00 AM)",
                    mensagem=f"Commit aprovado no repositório customizado B3 ({remote_sha[:7]}). A atualização foi agendada com segurança para as {AUTO_UPDATE_HOUR:02d}:{AUTO_UPDATE_MINUTE:02d} fora do horário do pregão.",
                    categoria="WATCHDOG_ALERT"
                )

        db.commit()
        return {
            "target": "custom",
            "current_commit": state.current_commit,
            "remote_commit": state.remote_commit,
            "update_available": state.update_available,
            "scheduled_update_at": state.scheduled_update_at
        }

    def execute_scheduled_update_if_due(self, db: Session):
        """Executa o auto-update caso o horário agendado tenha chegado"""
        state = db.query(WatchdogState).filter(
            WatchdogState.target == "custom",
            WatchdogState.update_available == True,
            WatchdogState.scheduled_update_at <= datetime.datetime.utcnow()
        ).first()

        if state:
            logger.info(f"[Watchdog Custom] Executando rotina segura de auto-update das 03:00 AM...")
            try:
                # Executa git pull de forma segura
                res = subprocess.run(["git", "pull"], capture_output=True, text=True, timeout=60)
                state.current_commit = state.remote_commit
                state.update_available = False
                state.scheduled_update_at = None
                db.commit()
                logger.info(f"[Watchdog Custom] Atualização concluída com sucesso: {res.stdout[:150]}")
            except Exception as e:
                logger.error(f"[Watchdog Custom] Falha durante auto-update seguro: {e}")

    def _fetch_github_latest_sha(self, repo: str) -> Optional[str]:
        """Consulta último commit do repositório no GitHub"""
        if not repo:
            return None
        url = f"https://api.github.com/repos/{repo}/commits/main"
        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.get(url, headers={"User-Agent": "TradingAgents-Watchdog"})
                if res.status_code == 200:
                    return res.json().get("sha")
                # Tenta branch master se main falhar
                res_master = client.get(f"https://api.github.com/repos/{repo}/commits/master", headers={"User-Agent": "TradingAgents-Watchdog"})
                if res_master.status_code == 200:
                    return res_master.json().get("sha")
        except Exception as e:
            logger.warning(f"[Watchdog] Falha ao consultar GitHub para {repo}: {e}")
        return None

    def _get_local_upstream_commit(self) -> Optional[str]:
        """Obtém hash do commit local do repositório upstream clonado"""
        try:
            res = subprocess.run(
                ["git", "-C", str(UPSTREAM_DIR), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return None

    def _get_local_git_commit(self) -> Optional[str]:
        """Obtém hash do commit local do repositório raiz"""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return "custom-v8.0.0"

_watchdog_instance = None

def get_dual_watchdog() -> DualWatchdogManager:
    global _watchdog_instance
    if _watchdog_instance is None:
        _watchdog_instance = DualWatchdogManager()
    return _watchdog_instance
