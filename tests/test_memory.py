import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.models import Asset, TradeMemory
from src.memory.settle_reflect import SettleReflectEngine

@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()

def test_settle_and_reflect_memory_recording_and_retrieval(db_session):
    engine = SettleReflectEngine()

    # Registra trade fechado em LOSS pelo robô técnico
    mem = engine.process_trade_feedback(
        db=db_session,
        ticker="VALE3",
        resultado="LOSS",
        motivo_grafico="Rompimento falso no suporte de R$ 60",
        lucro_prejuizo_pct=-2.5
    )

    assert mem.id is not None
    assert mem.ticker == "VALE3.SA"
    assert mem.resultado == "LOSS"
    assert "VALE3" in mem.licao_aprendida

    # Recupera lições para futura injeção no prompt
    lessons = engine.get_past_lessons(db_session, "VALE3")
    assert len(lessons) >= 1
    assert lessons[0]["resultado"] == "LOSS"
    assert "Rompimento falso" in lessons[0]["motivo_grafico"]
