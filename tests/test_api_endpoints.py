import pytest
from unittest.mock import MagicMock
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.models import User
from src.auth.security import get_password_hash
from src.schemas import LoginRequest, QueueDemandRequest, TradeFeedbackRequest, ApiKeyCreate, WebhookPingRequest
from src.web.api_routes import (
    json_login,
    receive_queue_demand,
    receive_trade_feedback,
    list_assets,
    add_key,
    get_watchdogs_status,
    ping_technical_robot_endpoint
)



@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    session = Session()

    # Cria usuário admin para testes
    admin = User(
        username="admin",
        hashed_password=get_password_hash("admin123"),
        is_active=True
    )
    session.add(admin)
    session.commit()

    yield session
    session.close()

def test_api_login_endpoint(db_session):
    req = LoginRequest(username="admin", password="admin123")
    res = json_login(req, db_session)
    assert "access_token" in res
    assert res["token_type"] == "bearer"

def test_api_queue_demand_endpoint(db_session):
    req = QueueDemandRequest(
        ativos=["PETR4", "VALE3"],
        prioridade="alta",
        origem="robo_tecnico_test"
    )
    res = receive_queue_demand(req, db_session)
    assert res.status == "queued"
    assert res.message == "Ativos na Fila"
    assert res.total_enfileirados == 2
    assert "PETR4" in res.ativos

def test_api_trade_feedback_memory_endpoint(db_session):
    req = TradeFeedbackRequest(
        ativo="BBDC4",
        resultado="WIN",
        motivo_grafico="Alvo de 3% atingido",
        lucro_prejuizo_pct=3.0
    )
    bg = MagicMock(spec=BackgroundTasks)
    res = receive_trade_feedback(req, bg, db_session)
    assert res.resultado == "WIN"
    assert len(res.licao_aprendida) > 0

def test_api_keys_and_assets_endpoints(db_session):
    admin_user = db_session.query(User).first()

    # Adiciona chave
    key_req = ApiKeyCreate(
        provider="gemini",
        label="Chave Teste",
        key_value="AIzaSy_fake_test_key_12345",
        daily_limit=500,
        priority=1
    )
    key_res = add_key(key_req, db_session, admin_user)
    assert key_res["message"] == "Chave adicionada ao pool com sucesso"

    # Lista ativos
    assets = list_assets(db_session, admin_user)
    assert isinstance(assets, list)

    # Watchdogs
    wd_status = get_watchdogs_status(db_session, admin_user)
    assert "upstream" in wd_status
    assert "custom" in wd_status

def test_api_webhook_ping_endpoint(db_session):
    admin_user = db_session.query(User).first()
    from unittest.mock import patch
    import httpx

    mock_resp = httpx.Response(status_code=200, text='{"status": "ok"}')
    with patch.object(httpx.Client, "post", return_value=mock_resp):
        req = WebhookPingRequest(target_url="http://localhost:5000/webhook/decisao")
        res = ping_technical_robot_endpoint(req, db_session, admin_user)
        assert res["ok"] is True
        assert res["status_code"] == 200
        assert res["target_url"] == "http://localhost:5000/webhook/decisao"


