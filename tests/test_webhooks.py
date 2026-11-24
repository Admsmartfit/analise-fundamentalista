from unittest.mock import patch
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.models import WebhookOutbox
from src.webhooks.typesafe import TypeSafeDecisionFormatter
from src.webhooks.dispatcher import WebhookDispatcher

@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()

def test_typesafe_decision_formatting():
    payload = TypeSafeDecisionFormatter.format_decision(
        ticker="PETR4.SA",
        status="autorizado",
        conviccao=0.88,
        validade_dias=7,
        tese_resumida="Excelente geração de caixa e dividendos sólidos.",
        indicadores={"ROE_pct": 25.4, "DY_pct": 14.2}
    )
    assert payload.ativo == "PETR4"
    assert payload.status == "autorizado"
    assert payload.conviccao == 0.88
    assert payload.validade_dias == 7
    assert payload.data_expiracao > payload.data_autorizacao

def test_webhook_outbox_queue_and_retry(db_session):
    dispatcher = WebhookDispatcher(target_url="http://invalid-endpoint-for-test.local/callback")
    decision = TypeSafeDecisionFormatter.format_decision(
        ticker="WEGE3",
        status="autorizado",
        conviccao=0.90,
        validade_dias=10,
        tese_resumida="Crescimento constante de receitas."
    )

    with patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("Connection refused")):
        entry = dispatcher.queue_decision(db_session, decision)
        assert entry.id is not None
        assert entry.status == "pending"
        assert entry.retry_count == 1
        assert "Connection refused" in entry.last_error

def test_webhook_ping_target_success_and_failure(db_session):
    dispatcher = WebhookDispatcher()

    # 1. Simula resposta bem sucedida
    mock_resp = httpx.Response(status_code=200, text='{"status": "ok"}')
    with patch.object(httpx.Client, "post", return_value=mock_resp):
        res = dispatcher.ping_target(db_session, "http://localhost:5000/webhook/decisao")
        assert res["ok"] is True
        assert res["status_code"] == 200
        assert "latency_ms" in res
        assert "status" in res["resposta"]

    # 2. Simula conexão recusada (servidor desligado)
    with patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("Conexão recusada")):
        res_fail = dispatcher.ping_target(db_session, "http://localhost:5000/webhook/decisao")
        assert res_fail["ok"] is False
        assert res_fail["status_code"] is None
        assert "Conexão recusada" in res_fail["erro"]




def test_webhook_usa_url_configurada_no_cockpit(db_session):
    from src.models import SystemSetting
    dispatcher = WebhookDispatcher(target_url="http://env-default.local/callback")
    assert dispatcher.resolve_target_url(db_session) == "http://env-default.local/callback"
    db_session.add(SystemSetting(key="technical_robot_webhook_url", value="http://robo.local:5000/decisao"))
    db_session.commit()
    assert dispatcher.resolve_target_url(db_session) == "http://robo.local:5000/decisao"


def test_forcar_retentativas_reenvia_falhas_com_url_atual(db_session):
    from src.models import SystemSetting
    dispatcher = WebhookDispatcher(target_url="http://antiga.local/cb")
    decision = TypeSafeDecisionFormatter.format_decision(
        ticker="ITUB4", status="autorizado", conviccao=0.8, validade_dias=5, tese_resumida="ok")
    with patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("down")):
        entry = dispatcher.queue_decision(db_session, decision)
    entry.status = "failed"
    db_session.add(SystemSetting(key="technical_robot_webhook_url", value="http://nova.local/cb"))
    db_session.commit()

    class _Ok:
        status_code = 200
        text = "ok"
    with patch.object(httpx.Client, "post", return_value=_Ok()) as post:
        assert dispatcher.force_retry_all(db_session) == 1
        assert post.call_args[0][0] == "http://nova.local/cb"
    db_session.refresh(entry)
    assert entry.status == "delivered"


def test_ping_e_reenvio_usam_endereco_novo(db_session):
    from src.models import SystemSetting
    from src.webhooks.dispatcher import normalize_url
    assert normalize_url(" localhost:8765/webhook/decisao ") == "http://localhost:8765/webhook/decisao"
    assert normalize_url("https://x.com/a") == "https://x.com/a"

    dispatcher = WebhookDispatcher(target_url="http://env.local/cb")
    setting = SystemSetting(key="technical_robot_webhook_url", value="http://errado.local/cb")
    db_session.add(setting)
    db_session.commit()
    decision = TypeSafeDecisionFormatter.format_decision(
        ticker="BBAS3", status="autorizado", conviccao=0.7, validade_dias=3, tese_resumida="ok")
    with patch.object(httpx.Client, "post", side_effect=httpx.ConnectError("down")):
        entry = dispatcher.queue_decision(db_session, decision)
    assert entry.target_url == "http://errado.local/cb"

    # Usuário corrige o endereço (sem http://)
    setting.value = "localhost:8765/webhook/decisao"
    db_session.commit()

    class _Ok:
        status_code = 200
        text = "pong"
    with patch.object(httpx.Client, "post", return_value=_Ok()) as post:
        assert dispatcher.ping_target(db_session)["target_url"] == "http://localhost:8765/webhook/decisao"
        assert dispatcher.ping_target(db_session, " localhost:9000/x")["target_url"] == "http://localhost:9000/x"
        dispatcher.attempt_delivery(db_session, entry.id)          # reenvio automático pendente
        assert post.call_args[0][0] == "http://localhost:8765/webhook/decisao"
    db_session.refresh(entry)
    assert entry.status == "delivered" and entry.target_url == "http://localhost:8765/webhook/decisao"
