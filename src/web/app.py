import os
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

from src.database import engine, Base, SessionLocal
from src.models import User, SystemSetting
from src.auth.security import get_password_hash
from src.config import (
    ADMIN_USERNAME, ADMIN_PASSWORD,
    TECHNICAL_ROBOT_WEBHOOK_URL, EVOLUTION_API_URL, EVOLUTION_API_KEY,
    EVOLUTION_INSTANCE, EVOLUTION_RECIPIENT_NUMBER, UPSTREAM_REPO, CUSTOM_REPO, APP_VERSION
)
from src.web.api_routes import router as api_router
from src.queue.worker import get_queue_worker
from src.watchdog.dual_watchdog import get_dual_watchdog

logger = logging.getLogger("web.app")

BASE_DIR = Path(__file__).resolve().parent

# Cria tabelas se não existirem
Base.metadata.create_all(bind=engine)

def seed_initial_data():
    """Garante existência de usuário administrador e configurações padrão"""
    db = SessionLocal()
    try:
        # Usuário Admin
        admin = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not admin:
            admin = User(
                username=ADMIN_USERNAME,
                hashed_password=get_password_hash(ADMIN_PASSWORD),
                is_active=True
            )
            db.add(admin)
            logger.info(f"[Init] Usuário inicial '{ADMIN_USERNAME}' criado com sucesso.")

        # Configurações do Sistema
        default_settings = {
            "technical_robot_webhook_url": TECHNICAL_ROBOT_WEBHOOK_URL,
            "evolution_api_url": EVOLUTION_API_URL,
            "evolution_api_key": EVOLUTION_API_KEY,
            "evolution_instance": EVOLUTION_INSTANCE,
            "evolution_recipient_number": EVOLUTION_RECIPIENT_NUMBER,
            "upstream_repo": UPSTREAM_REPO,
            "custom_repo": CUSTOM_REPO or "",
        }
        for k, v in default_settings.items():
            s = db.query(SystemSetting).filter(SystemSetting.key == k).first()
            if not s:
                db.add(SystemSetting(key=k, value=str(v)))

        db.commit()
    finally:
        db.close()

# Executa seed inicial
seed_initial_data()

# Agendador APScheduler para o Watchdog e Auto-update
scheduler = BackgroundScheduler()

def scheduled_watchdog_job():
    db = SessionLocal()
    try:
        watchdog = get_dual_watchdog()
        watchdog.check_upstream(db)
        watchdog.check_custom_repo(db)
        watchdog.execute_scheduled_update_if_due(db)
    except Exception as e:
        logger.error(f"[Scheduler] Erro na rotina de watchdog: {e}")
    finally:
        db.close()

# Roda watchdog periodicamente se não estiver em ambiente de teste
if os.getenv("TESTING") != "1":
    scheduler.add_job(scheduled_watchdog_job, "interval", minutes=30)
    scheduler.start()

# Worker assíncrono em segundo plano
worker_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task
    # Inicializa loop assíncrono do QueueWorker se não estiver em teste
    if os.getenv("TESTING") != "1":
        worker = get_queue_worker()
        worker_task = asyncio.create_task(worker.run_worker_loop())
        logger.info("[App] Servidor TradingAgents B3 & Cockpit inicializado com sucesso.")
    yield
    # Finalização
    if worker_task:
        worker = get_queue_worker()
        worker.stop()
        worker_task.cancel()
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("[App] Finalizando TradingAgents B3...")


app = FastAPI(
    title="TradingAgents B3 & Cockpit Web",
    description="Cérebro Estratégico Autorizador de Análise Fundamentalista para a B3",
    version=APP_VERSION,
    lifespan=None if os.getenv("TESTING") == "1" else lifespan
)


# CORS liberado para integração com dashboards e webhooks
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monta diretórios estáticos e templates
static_path = BASE_DIR / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

templates_path = BASE_DIR / "templates"
templates_path.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(templates_path))

# Registra rotas de API
app.include_router(api_router)

# Rotas de Interface Web (Cockpit)
@app.get("/", response_class=HTMLResponse)
def index_view(request: Request):
    """Cockpit Web Principal"""
    return templates.TemplateResponse(request, "index.html", {"version": APP_VERSION})

@app.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    """Tela de Autenticação Segura"""
    return templates.TemplateResponse(request, "login.html", {})
