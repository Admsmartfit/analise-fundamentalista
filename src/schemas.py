import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

# --- Schemas de Autenticação ---
class TokenSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int

class TokenDataSchema(BaseModel):
    username: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

class UserCreateSchema(BaseModel):
    username: str
    password: str

class UserResponseSchema(BaseModel):
    id: int
    username: str
    is_active: bool
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- Schemas da Smart Queue (Comunicação Bidirecional) ---
class QueueDemandRequest(BaseModel):
    """Payload recebido do Robô Técnico para reavaliar ativos"""
    ativos: List[str] = Field(..., min_length=1, description="Lista de tickers, ex: ['PETR4', 'VALE3']")
    prioridade: Optional[str] = Field("normal", description="normal, alta, urgente")
    origem: Optional[str] = Field("robo_tecnico", description="Identificador da origem da demanda")

class QueueDemandResponse(BaseModel):
    """Resposta imediata em milissegundos HTTP 200 liberando o robô técnico"""
    status: str = "queued"
    message: str = "Ativos na Fila"
    ativos: List[str]
    total_enfileirados: int
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class QueueItemResponse(BaseModel):
    id: int
    ticker: str
    prioridade: str
    status: str
    queued_at: datetime.datetime
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    error_message: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# --- TypeSafe Output: Callback de Decisão para o Robô Técnico ---
class DecisionCallbackPayload(BaseModel):
    """Formato rígido TypeSafe/JSON disparado via Webhook para o Robô Técnico"""
    ativo: str = Field(..., description="Ticker do ativo (ex: PETR4)")
    status: str = Field(..., description="'autorizado', 'rejeitado' ou 'pausa_analise'")
    conviccao: float = Field(..., ge=0.0, le=1.0, description="Nível de convicção da IA de 0.0 a 1.0")
    validade_dias: int = Field(..., ge=1, description="Dias em que esta autorização é válida")
    tese_resumida: str = Field(..., description="Resumo executivo da tese fundamentalista em PT-BR")
    indicadores_chave: Dict[str, Any] = Field(default_factory=dict, description="Métricas financeiras calculadas")
    data_autorizacao: datetime.datetime
    data_expiracao: datetime.datetime
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    id_analise: Optional[int] = None
    origem_decisao: Optional[str] = Field(None, description="Quem decidiu: 'IA: provedor/modelo', regra de contingência ou trava")
    fontes_consultadas: Optional[str] = Field(None, description="Fontes de dados que responderam nesta análise")

# --- Schemas de Memória de Aprendizado Contínuo (Settle-and-Reflect) ---
class TradeFeedbackRequest(BaseModel):
    """Payload recebido quando o robô técnico encerra um trade"""
    ativo: str = Field(..., description="Ticker negociado")
    resultado: str = Field(..., description="'WIN' ou 'LOSS'")
    motivo_grafico: Optional[str] = Field(None, description="Ex: 'Rompimento falso', 'Alvo atingido'")
    lucro_prejuizo_pct: Optional[float] = Field(None, description="Percentual de ganho/perda")
    detalhes: Optional[Dict[str, Any]] = None

class TradeMemoryResponse(BaseModel):
    id: int
    ticker: str
    resultado: str
    motivo_grafico: Optional[str]
    lucro_prejuizo_pct: Optional[float]
    licao_aprendida: str
    tese_original: Optional[str]
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

# --- Schemas de Gestão de Ativos e Cockpit ---
class AssetResponse(BaseModel):
    id: int
    ticker: str
    nome: Optional[str]
    setor: Optional[str]
    status_analise: str
    conviccao: float
    validade_dias: int
    data_autorizacao: Optional[datetime.datetime]
    data_expiracao: Optional[datetime.datetime]
    tese_resumida: Optional[str]
    indicadores: Optional[Dict[str, Any]]
    fonte_dados: Optional[str]
    dias_restantes: Optional[int] = None
    ultima_atualizacao: datetime.datetime
    decisao_origem: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class SourceToggleRequest(BaseModel):
    enabled: bool


class CustomRSSCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=100)
    url_template: str = Field(..., min_length=10, max_length=500,
                              description="URL do feed RSS. Pode conter {ticker} ou {empresa} para buscas.")


class AssetCreateUpdate(BaseModel):
    ticker: str
    nome: Optional[str] = None
    setor: Optional[str] = None

# --- Schemas de Key Pool ---
class ApiKeyCreate(BaseModel):
    provider: str # gemini, claude, deepseek, openai, groq
    label: Optional[str] = None
    key_value: str
    daily_limit: Optional[int] = 1000
    priority: Optional[int] = 1

class ApiKeyResponse(BaseModel):
    id: int
    provider: str
    label: Optional[str]
    key_masked: str
    is_active: bool
    rate_limit_hit: bool
    daily_limit: int
    current_usage: int
    priority: int
    last_used_at: Optional[datetime.datetime]
    model_config = ConfigDict(from_attributes=True)

# --- Schemas de Configurações e Logs ---
class WebhookPingRequest(BaseModel):
    target_url: Optional[str] = Field(None, description="URL do webhook para teste (opcional, usa a cadastrada se omitido)")

class SystemSettingUpdate(BaseModel):

    key: str
    value: str

class AuditLogResponse(BaseModel):
    id: int
    level: str
    category: str
    message: str
    details_json: Optional[Dict[str, Any]]
    created_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)

class WatchdogStatusResponse(BaseModel):
    target: str
    current_commit: Optional[str]
    remote_commit: Optional[str]
    update_available: bool
    scheduled_update_at: Optional[datetime.datetime]
    last_checked_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)



class NetworkConfigUpdate(BaseModel):
    port: int = Field(..., ge=1024, le=65535, description="Porta do Cérebro (Cockpit + API)")
    host: str = Field("127.0.0.1", description="127.0.0.1 (só este computador) ou 0.0.0.0 (rede)")
