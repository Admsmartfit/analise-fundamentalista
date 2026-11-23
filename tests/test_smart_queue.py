import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.models import QueueItem, Asset
from unittest.mock import MagicMock
from src.b3.data_engine import B3DataEngine
from src.queue.smart_queue import SmartQueueManager
from src.queue.worker import QueueWorker

@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()

def test_smart_queue_enqueue_and_batch_processing(db_session):
    q_mgr = SmartQueueManager()
    
    # Enfileira demanda de 3 ativos
    resp = q_mgr.enqueue_assets(db_session, ["PETR4", "VALE3", "ITUB4"], prioridade="normal")
    assert resp.status == "queued"
    assert resp.total_enfileirados == 3
    assert len(resp.ativos) == 3

    # Checa estado da fila
    status = q_mgr.get_queue_status(db_session)
    assert status["aguardando"] == 3
    assert status["em_processamento"] == 0

    # Inicializa worker com mock do b3_engine para teste unitário ultrarrápido
    mock_b3 = MagicMock(spec=B3DataEngine)
    mock_b3.get_asset_data.return_value = (
        {
            "ticker": "PETR4.SA",
            "nome": "Petrobras",
            "setor": "Petróleo e Gás",
            "preco_atual": 36.50,
            "indicadores": {"PL": 4.5, "ROE_pct": 28.0, "DY_pct": 16.0, "Margem_Liquida_pct": 22.0},
            "noticias": ["Resultados sólidos no trimestre"],
            "cvm": {},
            "fonte_utilizada": "YahooFinance"
        },
        "sucesso_primario"
    )

    worker = QueueWorker(batch_size=2, b3_engine=mock_b3)
    processed_count = worker.process_next_batch(db_session)
    assert processed_count == 2

    # Verifica que restou 1 na fila aguardando
    status_after = q_mgr.get_queue_status(db_session)
    assert status_after["aguardando"] == 1

