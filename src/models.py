import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, JSON, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from src.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), unique=True, index=True, nullable=False) # Ex: PETR4.SA
    nome = Column(String(100), nullable=True)
    setor = Column(String(100), nullable=True)
    status_analise = Column(String(30), default="pendente") # autorizado, rejeitado, pausa_analise, pendente, em_analise
    conviccao = Column(Float, default=0.0) # 0.0 a 1.0
    validade_dias = Column(Integer, default=7)
    data_autorizacao = Column(DateTime, nullable=True)
    data_expiracao = Column(DateTime, nullable=True)
    tese_resumida = Column(Text, nullable=True) # Resumo executivo em PT-BR
    tese_detalhada = Column(Text, nullable=True)
    indicadores = Column(JSON, default=dict) # P/L, ROE, DY, Margem Líquida, etc.
    fonte_dados = Column(String(50), default="CVM") # CVM, YahooFinance, StatusInvest, Scraping
    ultima_atualizacao = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relacionamento com histórico de memórias pós-morte
    memorias = relationship("TradeMemory", back_populates="asset", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(30), nullable=False) # gemini, claude, deepseek, openai, groq
    label = Column(String(50), nullable=True)
    key_value = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    rate_limit_hit = Column(Boolean, default=False)
    daily_limit = Column(Integer, default=1000) # Cota diária estimada de chamadas
    current_usage = Column(Integer, default=0)
    priority = Column(Integer, default=1) # Menor número = maior prioridade
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    rate_limit_reset_at = Column(DateTime, nullable=True)


class QueueItem(Base):
    __tablename__ = "queue_items"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    prioridade = Column(String(20), default="normal") # normal, alta, urgente
    status = Column(String(20), default="queued") # queued, processing, completed, failed
    request_source = Column(String(50), default="technical_robot")
    queued_at = Column(DateTime, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


class WebhookOutbox(Base):
    __tablename__ = "webhook_outbox"

    id = Column(Integer, primary_key=True, index=True)
    target_url = Column(String(500), nullable=False)
    payload_json = Column(JSON, nullable=False)
    status = Column(String(20), default="pending") # pending, delivered, failed
    retry_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    delivered_at = Column(DateTime, nullable=True)


class TradeMemory(Base):
    __tablename__ = "trade_memories"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), ForeignKey("assets.ticker"), nullable=False, index=True)
    resultado = Column(String(10), nullable=False) # WIN, LOSS
    motivo_grafico = Column(String(255), nullable=True) # Ex: "Rompimento falso", "Stop acionado por volatilidade"
    lucro_prejuizo_pct = Column(Float, nullable=True)
    licao_aprendida = Column(Text, nullable=False) # Síntese da IA refletindo sobre a tese
    tese_original = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    asset = relationship("Asset", back_populates="memorias")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), default="INFO") # INFO, WARNING, ERROR, CRITICAL
    category = Column(String(50), default="GENERAL") # QUEUE, KEY_POOL, WEBHOOK, WATCHDOG, AUTH, ANALYSIS
    message = Column(Text, nullable=False)
    details_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class WatchdogState(Base):
    __tablename__ = "watchdog_states"

    id = Column(Integer, primary_key=True, index=True)
    target = Column(String(30), unique=True, nullable=False) # upstream, custom
    current_commit = Column(String(50), nullable=True)
    remote_commit = Column(String(50), nullable=True)
    update_available = Column(Boolean, default=False)
    scheduled_update_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, default=datetime.datetime.utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class DataSourceConfig(Base):
    """Configuração e saúde de cada fonte de dados (embutida ou RSS cadastrado pelo usuário)."""
    __tablename__ = "data_source_configs"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(String(50), unique=True, nullable=False, index=True)
    enabled = Column(Boolean, default=True)
    # Campos só usados por fontes RSS cadastradas pelo usuário
    is_custom = Column(Boolean, default=False)
    nome = Column(String(100), nullable=True)
    url_template = Column(String(500), nullable=True)
    # Saúde (atualizada a cada coleta ou teste)
    last_status = Column(String(20), nullable=True)   # ok, erro
    last_checked_at = Column(DateTime, nullable=True)
    last_ok_at = Column(DateTime, nullable=True)
    last_latency_ms = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    last_resumo = Column(Text, nullable=True)
    ok_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)


class AnalysisRun(Base):
    """Uma análise de ativo: o que cada fonte trouxe, a triagem e quem decidiu (IA ou regra)."""
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    status_coleta = Column(String(30), nullable=True)
    fontes_json = Column(JSON, default=list)        # [SourceResult.to_dict(), ...]
    avisos_json = Column(JSON, default=list)        # avisos de validação de dados
    triagem_texto = Column(Text, nullable=True)
    triagem_origem = Column(String(100), nullable=True)
    decisao_origem = Column(String(100), nullable=True)  # ex.: "IA: gemini/gemini-flash-lite-latest" ou "Regra de contingência"
    erro_llm = Column(Text, nullable=True)
    veredito_json = Column(JSON, nullable=True)
