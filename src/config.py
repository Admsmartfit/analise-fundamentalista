import os
from pathlib import Path
from dotenv import load_dotenv

# Pasta do código (na versão instalada: <instalação>\app)
BASE_DIR = Path(__file__).resolve().parent.parent

# Pasta de dados (banco, .env, cache, backups, logs). Na versão instalada o launcher define
# TA_DATA_DIR=<instalação>\data, separada do código: a atualização troca o código sem tocar nos dados.
DATA_DIR = Path(os.getenv("TA_DATA_DIR") or BASE_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Carrega variáveis de ambiente do .env (primeiro o da pasta de dados)
load_dotenv(dotenv_path=DATA_DIR / ".env")
if DATA_DIR != BASE_DIR:
    load_dotenv(dotenv_path=BASE_DIR / ".env")

# Versão do sistema (arquivo VERSION na raiz do código)
_version_file = BASE_DIR / "VERSION"
APP_VERSION = _version_file.read_text(encoding="utf-8").strip() if _version_file.exists() else "dev"

# Raiz da instalação (existe só na versão instalada: <raiz>\runtime\python.exe + <raiz>\app)
_root = BASE_DIR.parent
INSTALL_ROOT = _root if (_root / "runtime" / "python.exe").exists() and BASE_DIR.name == "app" else None

# Cache de arquivos baixados (CVM etc.)
CACHE_DIR = DATA_DIR / "cache" if os.getenv("TA_DATA_DIR") else BASE_DIR / "data" / "cache"

# Canal de atualização padrão (pasta ou URL com latest.json); pode ser trocado no Cockpit
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "")

# Configurações de Segurança e JWT
SECRET_KEY = os.getenv("SECRET_KEY", "tradingagents_b3_default_secret_key_2026_change_in_prod")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")) # 24 horas
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# Servidor Web
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# Banco de Dados
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'tradingagents.db').as_posix()}")

# Modelos LLM (aliases "latest" acompanham as versões atuais e evitam 404 quando o provedor desativa um modelo)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
# Tentados em ordem quando o principal está sobrecarregado (503) ou desativado (404)
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-flash-latest,gemini-2.5-flash-lite").split(",") if m.strip()]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

# Robô Técnico e Webhooks
TECHNICAL_ROBOT_WEBHOOK_URL = os.getenv("TECHNICAL_ROBOT_WEBHOOK_URL", "http://localhost:5000/webhook/decisao")
WEBHOOK_MAX_RETRIES = int(os.getenv("WEBHOOK_MAX_RETRIES", "5"))
WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
WEBHOOK_RETRY_INTERVALS = [60, 120, 300, 900, 1800] # Segundos entre retentativas

# WhatsApp / Evolution API
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "tradingagents")
EVOLUTION_RECIPIENT_NUMBER = os.getenv("EVOLUTION_RECIPIENT_NUMBER", "")

# Watchdogs
UPSTREAM_REPO = os.getenv("UPSTREAM_REPO", "TauricResearch/TradingAgents")
CUSTOM_REPO = os.getenv("CUSTOM_REPO", "")
AUTO_UPDATE_HOUR = int(os.getenv("AUTO_UPDATE_HOUR", "3"))
AUTO_UPDATE_MINUTE = int(os.getenv("AUTO_UPDATE_MINUTE", "0"))

# Diretório Upstream
UPSTREAM_DIR = BASE_DIR / "upstream" / "TradingAgents"
