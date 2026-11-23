import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database import Base
from src.models import ApiKey
from src.llm.key_pool import KeyPoolManager

@pytest.fixture
def db_session():
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.close()

def test_key_pool_hot_swap_and_exhaustion(db_session):
    manager = KeyPoolManager()
    
    # Pool vazio inicialmente
    assert manager.is_pool_exhausted(db_session) is True

    # Adiciona 2 chaves
    key1 = manager.add_key(db_session, "gemini", "AIzaSy_key_1", label="Chave 1", priority=1)
    key2 = manager.add_key(db_session, "gemini", "AIzaSy_key_2", label="Chave 2", priority=2)

    assert manager.is_pool_exhausted(db_session) is False

    # Pega primeira chave disponível (prioridade 1)
    active = manager.get_available_key(db_session, "gemini")
    assert active.id == key1.id

    # Rate limit na chave 1 aciona hot-swap para a chave 2
    has_remaining = manager.mark_rate_limited(db_session, key1.id)
    assert has_remaining is True

    next_active = manager.get_available_key(db_session, "gemini")
    assert next_active.id == key2.id

    # Rate limit na chave 2 esgota o pool
    has_remaining_2 = manager.mark_rate_limited(db_session, key2.id)
    assert has_remaining_2 is False
    assert manager.is_pool_exhausted(db_session) is True
