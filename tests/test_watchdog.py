import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.models import WatchdogState
from src.watchdog.dual_watchdog import DualWatchdogManager

@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()

def test_watchdog_state_tracking(db_session):
    manager = DualWatchdogManager()
    
    # Mocking SHA retrieval
    manager._fetch_github_latest_sha = lambda repo: "abc123456789"
    manager._get_local_upstream_commit = lambda: "orig111111111"

    status_up = manager.check_upstream(db_session)
    assert status_up["target"] == "upstream"
    assert status_up["update_available"] is True
    assert status_up["remote_commit"] == "abc123456789"


def test_upstream_sem_clone_local_nao_gera_alarme_falso(db_session):
    from src.watchdog.dual_watchdog import DualWatchdogManager
    from unittest.mock import MagicMock
    manager = DualWatchdogManager(evolution_client=MagicMock())
    manager._get_local_upstream_commit = lambda: None          # versão instalada: sem pasta upstream
    manager._fetch_github_latest_sha = lambda repo: "abc1234567"
    st = manager.check_upstream(db_session)
    assert st["update_available"] is False and st["current_commit"] == "abc1234567"
    manager._fetch_github_latest_sha = lambda repo: "def7654321"  # commit novo de verdade => alerta
    assert manager.check_upstream(db_session)["update_available"] is True
