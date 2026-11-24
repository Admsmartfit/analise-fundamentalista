import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import (
    User, Asset, ApiKey, QueueItem, WebhookOutbox, TradeMemory, AuditLog, WatchdogState, SystemSetting,
    DataSourceConfig, AnalysisRun
)
from src.schemas import (
    TokenSchema, LoginRequest, QueueDemandRequest, QueueDemandResponse,
    QueueItemResponse, TradeFeedbackRequest, TradeMemoryResponse,
    AssetResponse, AssetCreateUpdate, ApiKeyCreate, ApiKeyResponse,
    SystemSettingUpdate, AuditLogResponse, WatchdogStatusResponse,
    SourceToggleRequest, CustomRSSCreate, WebhookPingRequest
)

from fastapi import UploadFile, File
from src.config import APP_VERSION
from src.updater import manager as update_manager
from src.sources import registry as source_registry
from src.b3.data_engine import B3DataEngine
from src.b3.yahoo_connector import YahooConnector
from src.auth.security import (
    authenticate_user, create_access_token, get_current_user, get_password_hash
)
from src.queue.smart_queue import get_smart_queue
from src.queue.worker import get_queue_worker
from src.memory.settle_reflect import get_settle_reflect_engine
from src.llm.key_pool import get_key_pool_manager
from src.webhooks.dispatcher import get_webhook_dispatcher
from src.watchdog.dual_watchdog import get_dual_watchdog

router = APIRouter(prefix="/api")

# ==========================================
# 1. AUTENTICAÇÃO E SESSÃO (JWT)
# ==========================================
@router.post("/auth/token", response_model=TokenSchema)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "expires_in_minutes": 1440}

@router.post("/auth/login", response_model=TokenSchema)
def json_login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos"
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "expires_in_minutes": 1440}

@router.get("/auth/me")
def read_current_user(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "is_active": current_user.is_active}


# ==========================================
# 2. SMART QUEUE (COMUNICAÇÃO BIDIRECIONAL)
# ==========================================
@router.post("/queue/demand", response_model=QueueDemandResponse)
def receive_queue_demand(payload: QueueDemandRequest, db: Session = Depends(get_db)):
    """
    Endpoint de recepção do Robô Técnico:
    Responde em milissegundos com HTTP 200 liberando o robô,
    e enfileira os ativos para o worker processar em lotes.
    """
    queue_mgr = get_smart_queue()
    resp = queue_mgr.enqueue_assets(
        db=db,
        ativos=payload.ativos,
        prioridade=payload.prioridade or "normal",
        origem=payload.origem or "robo_tecnico"
    )
    return resp

@router.get("/queue/status")
def get_queue_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Métricas em tempo real para a barra de progresso do Cockpit"""
    queue_mgr = get_smart_queue()
    return queue_mgr.get_queue_status(db)

@router.get("/queue/items", response_model=List[QueueItemResponse])
def get_queue_items(limit: int = 50, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(QueueItem).order_by(QueueItem.id.desc()).limit(limit).all()


# ==========================================
# 3. MEMÓRIA CONTÍNUA (SETTLE-AND-REFLECT)
# ==========================================
@router.post("/memory/feedback", response_model=TradeMemoryResponse)
def receive_trade_feedback(
    payload: TradeFeedbackRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Recebe encerramento de trade (WIN/LOSS) do robô técnico e
    aciona a reflexão pós-morte para aprendizado contínuo.
    """
    memory_engine = get_settle_reflect_engine()
    memory_record = memory_engine.process_trade_feedback(
        db=db,
        ticker=payload.ativo,
        resultado=payload.resultado,
        motivo_grafico=payload.motivo_grafico,
        lucro_prejuizo_pct=payload.lucro_prejuizo_pct,
        detalhes=payload.detalhes
    )
    return memory_record

@router.get("/memory/lessons", response_model=List[TradeMemoryResponse])
def list_lessons(ticker: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(TradeMemory)
    if ticker:
        clean = ticker.upper().replace(".SA", "")
        query = query.filter((TradeMemory.ticker == f"{clean}.SA") | (TradeMemory.ticker == clean))
    return query.order_by(TradeMemory.id.desc()).limit(limit).all()


# ==========================================
# 4. GERENCIADOR B3 & ATIVOS
# ==========================================
@router.get("/assets", response_model=List[AssetResponse])
def list_assets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    assets = db.query(Asset).order_by(Asset.ticker.asc()).all()
    now = datetime.datetime.utcnow()
    origem_por_ticker = {}
    for run in db.query(AnalysisRun).order_by(AnalysisRun.id.desc()).all():
        origem_por_ticker.setdefault(run.ticker, run.decisao_origem)
    res = []
    for a in assets:
        dias_restantes = None
        if a.data_expiracao:
            delta = (a.data_expiracao - now).days
            dias_restantes = max(0, delta)
        
        res.append(AssetResponse(
            id=a.id,
            ticker=a.ticker,
            nome=a.nome,
            setor=a.setor,
            status_analise=a.status_analise or "pendente",
            conviccao=a.conviccao or 0.0,
            validade_dias=a.validade_dias or 7,
            data_autorizacao=a.data_autorizacao,
            data_expiracao=a.data_expiracao,
            tese_resumida=a.tese_resumida,
            indicadores=a.indicadores,
            fonte_dados=a.fonte_dados,
            dias_restantes=dias_restantes,
            ultima_atualizacao=a.ultima_atualizacao or now,
            decisao_origem=origem_por_ticker.get(a.ticker.upper().replace(".SA", ""))
        ))
    return res

@router.post("/assets")
def create_or_update_asset(payload: AssetCreateUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticker = payload.ticker.strip().upper()
    if not ticker.endswith(".SA") and not ticker.startswith("^"):
        ticker = f"{ticker}.SA"

    asset = db.query(Asset).filter(Asset.ticker == ticker).first()
    if not asset:
        asset = Asset(ticker=ticker, nome=payload.nome or ticker.replace(".SA", ""), setor=payload.setor)
        db.add(asset)
    else:
        if payload.nome:
            asset.nome = payload.nome
        if payload.setor:
            asset.setor = payload.setor
    db.commit()
    return {"message": "Ativo salvo com sucesso", "ticker": ticker}

@router.post("/assets/{ticker}/analyze")
def trigger_immediate_analysis(ticker: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Coloca o ativo com alta prioridade na fila de análise imediata"""
    queue_mgr = get_smart_queue()
    resp = queue_mgr.enqueue_assets(db=db, ativos=[ticker], prioridade="alta", origem="cockpit_manual")
    return resp


@router.get("/assets/{ticker}/sources")
def get_asset_sources(ticker: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Resumo por fonte das últimas análises do ativo (o que cada fonte trouxe e quem decidiu)."""
    from src.queue.worker import RUNS_POR_ATIVO
    clean = ticker.upper().replace(".SA", "")
    runs = (db.query(AnalysisRun).filter(AnalysisRun.ticker == clean)
            .order_by(AnalysisRun.id.desc()).limit(RUNS_POR_ATIVO).all())
    return [{
        "id": r.id,
        "created_at": r.created_at,
        "status_coleta": r.status_coleta,
        "fontes": r.fontes_json or [],
        "avisos": r.avisos_json or [],
        "triagem_texto": r.triagem_texto,
        "triagem_origem": r.triagem_origem,
        "decisao_origem": r.decisao_origem,
        "erro_llm": r.erro_llm,
        "veredito": r.veredito_json,
    } for r in runs]


# ==========================================
# 4b. FONTES DE DADOS (listar, testar, ligar/desligar, cadastrar RSS)
# ==========================================
def _source_row(fonte, cfg) -> Dict[str, Any]:
    d = fonte.info()
    d.update({
        "enabled": bool(cfg.enabled) if cfg else True,
        "last_status": cfg.last_status if cfg else None,
        "last_checked_at": cfg.last_checked_at if cfg else None,
        "last_ok_at": cfg.last_ok_at if cfg else None,
        "last_latency_ms": cfg.last_latency_ms if cfg else None,
        "last_error": cfg.last_error if cfg else None,
        "last_resumo": cfg.last_resumo if cfg else None,
        "ok_count": (cfg.ok_count or 0) if cfg else 0,
        "fail_count": (cfg.fail_count or 0) if cfg else 0,
    })
    return d


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    source_registry.ensure_configs(db)
    configs = {c.source_id: c for c in db.query(DataSourceConfig).all()}
    return [_source_row(f, configs.get(f.id)) for f in source_registry.build_sources(db)]


@router.post("/sources/test-all")
def test_all_sources(ticker: str = "PETR4", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Testa todas as fontes (inclusive desligadas) e mostra o que a IA receberia consolidado."""
    normalized = YahooConnector.normalize_ticker(ticker)
    ids = [f.id for f in source_registry.build_sources(db)]
    resultados = source_registry.collect(db, normalized, only=ids)
    enabled = {c.source_id for c in db.query(DataSourceConfig).filter(DataSourceConfig.enabled == True).all()}
    dados, status_coleta = B3DataEngine.consolidate(normalized, [r for r in resultados if r.fonte_id in enabled])
    return {
        "ticker": normalized,
        "resultados": [r.to_dict() for r in resultados],
        "consolidado": {
            "status_coleta": status_coleta,
            "preco_atual": dados.get("preco_atual"),
            "indicadores": dados.get("indicadores"),
            "indicadores_fontes": dados.get("indicadores_fontes"),
            "avisos": dados.get("avisos"),
            "qtd_noticias": len(dados.get("noticias") or []),
            "fonte_utilizada": dados.get("fonte_utilizada"),
        },
    }


@router.post("/sources/{source_id}/test")
def test_one_source(source_id: str, ticker: str = "PETR4", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = source_registry.test_source(db, source_id, YahooConnector.normalize_ticker(ticker))
    if not result:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    return result.to_dict()


@router.patch("/sources/{source_id}")
def toggle_source(source_id: str, payload: SourceToggleRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    source_registry.ensure_configs(db)
    cfg = db.query(DataSourceConfig).filter(DataSourceConfig.source_id == source_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    cfg.enabled = payload.enabled
    db.commit()
    return {"message": "Fonte ligada" if payload.enabled else "Fonte desligada", "source_id": source_id}


@router.post("/sources")
def add_custom_source(payload: CustomRSSCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    url = payload.url_template.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="A URL do feed deve começar com http:// ou https://")
    cfg = source_registry.add_custom_rss(db, payload.nome, url)
    return {"message": "Fonte RSS cadastrada", "source_id": cfg.source_id}


@router.delete("/sources/{source_id}")
def delete_custom_source(source_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cfg = db.query(DataSourceConfig).filter(DataSourceConfig.source_id == source_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    if not cfg.is_custom:
        raise HTTPException(status_code=400, detail="Fontes embutidas não podem ser removidas; desligue-as.")
    db.delete(cfg)
    db.commit()
    return {"message": "Fonte removida"}


# ==========================================
# 5. KEY POOL & ORÇAMENTO
# ==========================================
@router.get("/keys", response_model=List[ApiKeyResponse])
def list_keys(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    keys = db.query(ApiKey).order_by(ApiKey.priority.asc()).all()
    res = []
    for k in keys:
        masked = f"{k.key_value[:4]}...{k.key_value[-4:]}" if len(k.key_value) > 8 else "***"
        res.append(ApiKeyResponse(
            id=k.id,
            provider=k.provider,
            label=k.label,
            key_masked=masked,
            is_active=k.is_active,
            rate_limit_hit=k.rate_limit_hit,
            daily_limit=k.daily_limit or 1000,
            current_usage=k.current_usage or 0,
            priority=k.priority or 1,
            last_used_at=k.last_used_at
        ))
    return res

@router.post("/keys")
def add_key(payload: ApiKeyCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pool_mgr = get_key_pool_manager()
    key_obj = pool_mgr.add_key(
        db=db,
        provider=payload.provider,
        key_value=payload.key_value,
        label=payload.label,
        daily_limit=payload.daily_limit or 1000,
        priority=payload.priority or 1
    )
    return {"message": "Chave adicionada ao pool com sucesso", "id": key_obj.id, "provider": key_obj.provider}

@router.delete("/keys/{key_id}")
def delete_key(key_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    key_obj = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key_obj:
        raise HTTPException(status_code=404, detail="Chave não encontrada")
    db.delete(key_obj)
    db.commit()
    return {"message": "Chave removida do pool"}


# ==========================================
# 6. WEBHOOKS OUTBOX & RETENTATIVAS
# ==========================================
@router.get("/webhooks/outbox")
def list_outbox(limit: int = 50, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(WebhookOutbox).order_by(WebhookOutbox.id.desc()).limit(limit).all()

@router.post("/webhooks/retry-all")
def force_retry_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    dispatcher = get_webhook_dispatcher()
    total = dispatcher.force_retry_all(db)
    return {"message": "Processamento de retentativas executado", "reenviados": total}

@router.post("/webhooks/test-ping")
def ping_technical_robot_endpoint(payload: Optional[WebhookPingRequest] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Testa a conectividade com o robô técnico em tempo real."""
    dispatcher = get_webhook_dispatcher()
    url = payload.target_url if payload and payload.target_url else None
    return dispatcher.ping_target(db, target_url=url)




# ==========================================
# 7. WATCHDOG DUPLO
# ==========================================
@router.get("/watchdog/status")
def get_watchdogs_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    watchdog = get_dual_watchdog()
    up = watchdog.check_upstream(db)
    cust = watchdog.check_custom_repo(db)
    return {"upstream": up, "custom": cust}

@router.post("/watchdog/check")
def trigger_watchdog_check(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    watchdog = get_dual_watchdog()
    up = watchdog.check_upstream(db)
    cust = watchdog.check_custom_repo(db)
    return {"message": "Verificação concluída", "upstream": up, "custom": cust}


# ==========================================
# 8. LOGS DE AUDITORIA & CONFIGURAÇÕES
# ==========================================
@router.get("/logs", response_model=List[AuditLogResponse])
def get_audit_logs(limit: int = 100, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()

@router.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    settings = db.query(SystemSetting).all()
    return {s.key: s.value for s in settings}

@router.post("/settings")
def update_setting(payload: SystemSettingUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    setting = db.query(SystemSetting).filter(SystemSetting.key == payload.key).first()
    if not setting:
        setting = SystemSetting(key=payload.key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    db.commit()
    return {"message": "Configuração atualizada com sucesso"}


# ==========================================
# 9. SAÚDE E ATUALIZAÇÃO DO SISTEMA
# ==========================================
@router.get("/health")
def health():
    """Público: usado pelo launcher e pelo atualizador para saber se o servidor subiu e em qual versão."""
    return {"status": "ok", "version": APP_VERSION, "installed": update_manager.installed_mode()}


@router.get("/update/status")
def update_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    st = update_manager.read_status()
    st["canal"] = update_manager.get_channel(db)
    return st


@router.post("/update/check")
def update_check(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return update_manager.check(db)
    except update_manager.UpdateError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/update/apply")
def update_apply(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Baixa o pacote do canal, confere o SHA-256, faz backup do banco e reinicia na versão nova."""
    try:
        info = update_manager.check(db)
        if not info["tem_atualizacao"]:
            raise update_manager.UpdateError(f"Já está na versão mais recente ({info['versao_instalada']}).")
        if not update_manager.installed_mode():
            raise update_manager.UpdateError("A atualização automática só funciona na versão instalada pelo instalador.")
        pacote = update_manager.download_package(db)
        res = update_manager.launch_apply(pacote)
    except update_manager.UpdateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add(AuditLog(level="WARNING", category="UPDATE", message=res["message"], details_json=res))
    db.commit()
    return res


@router.post("/update/upload")
async def update_upload(file: UploadFile = File(...), db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """Atualização manual: envia o .zip do pacote (TradingAgentsB3-app-X.Y.Z.zip)."""
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Envie o arquivo .zip do pacote de atualização.")
    update_manager.UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    destino = update_manager.UPDATES_DIR / "pacote-enviado.zip"
    with open(destino, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    try:
        res = update_manager.launch_apply(destino)
    except update_manager.UpdateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add(AuditLog(level="WARNING", category="UPDATE", message=res["message"], details_json=res))
    db.commit()
    return res
