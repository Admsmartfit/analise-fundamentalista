import time
import logging
import datetime
import asyncio
from typing import Optional
from sqlalchemy.orm import Session
from src.database import SessionLocal
from src.models import QueueItem, Asset, AuditLog, AnalysisRun
from src.b3.data_engine import B3DataEngine, get_b3_data_engine
from src.llm.model_cascade import ModelCascadeManager, get_model_cascade
from src.memory.settle_reflect import SettleReflectEngine, get_settle_reflect_engine
from src.webhooks.typesafe import TypeSafeDecisionFormatter
from src.webhooks.dispatcher import WebhookDispatcher, get_webhook_dispatcher

logger = logging.getLogger("queue.worker")

RUNS_POR_ATIVO = 5  # histórico de coletas guardado por ativo (limita o tamanho do banco)


def save_analysis_run(db: Session, ticker: str, dados: dict, status_coleta: str,
                      triagem_texto=None, triagem_meta=None, decisao_meta=None, veredito=None) -> AnalysisRun:
    """Guarda o que cada fonte trouxe e quem decidiu; mantém só as últimas RUNS_POR_ATIVO."""
    triagem_meta = triagem_meta or {}
    decisao_meta = decisao_meta or {}
    erros = [e for e in (triagem_meta.get("erro"), decisao_meta.get("erro")) if e]
    run = AnalysisRun(
        ticker=ticker,
        status_coleta=status_coleta,
        fontes_json=dados.get("fontes", []),
        avisos_json=dados.get("avisos", []),
        triagem_texto=triagem_texto,
        triagem_origem=triagem_meta.get("origem"),
        decisao_origem=decisao_meta.get("origem") or ("Trava de segurança" if status_coleta == "pausa_analise" else None),
        erro_llm=" | ".join(dict.fromkeys(erros)) or None,
        veredito_json=veredito,
    )
    db.add(run)
    db.flush()
    antigos = (db.query(AnalysisRun).filter(AnalysisRun.ticker == ticker)
               .order_by(AnalysisRun.id.desc()).offset(RUNS_POR_ATIVO).all())
    for a in antigos:
        db.delete(a)
    return run

class QueueWorker:
    """
    Worker em Segundo Plano para a Smart Queue.
    Processa a fila em lotes controlados (ex: 2 papéis por vez) para manter
    respeito a Rate Limits de APIs e estabilidade do sistema.
    """
    def __init__(
        self,
        batch_size: int = 2,
        sleep_interval: float = 3.0,
        b3_engine: Optional[B3DataEngine] = None,
        cascade: Optional[ModelCascadeManager] = None,
        memory_engine: Optional[SettleReflectEngine] = None,
        dispatcher: Optional[WebhookDispatcher] = None
    ):
        self.batch_size = batch_size
        self.sleep_interval = sleep_interval
        self.b3_engine = b3_engine or get_b3_data_engine()
        self.cascade = cascade or get_model_cascade()
        self.memory_engine = memory_engine or get_settle_reflect_engine()
        self.dispatcher = dispatcher or get_webhook_dispatcher()
        self.is_running = False

    def process_next_batch(self, db: Session) -> int:
        """
        Localiza os próximos itens da fila por prioridade ('urgente' > 'alta' > 'normal')
        e executa a análise completa de ponta a ponta.
        Retorna a quantidade de itens processados no lote.
        """
        # Ordena prioridades: urgente = 1, alta = 2, normal = 3
        items = db.query(QueueItem).filter(QueueItem.status == "queued").all()
        if not items:
            return 0

        def priority_weight(item):
            weights = {"urgente": 1, "alta": 2, "normal": 3}
            return (weights.get(item.prioridade, 3), item.queued_at)

        sorted_items = sorted(items, key=priority_weight)[:self.batch_size]

        for item in sorted_items:
            self._process_single_item(db, item)

        return len(sorted_items)

    def _process_single_item(self, db: Session, item: QueueItem):
        """Processa um ativo individual da fila"""
        ticker = item.ticker
        item.status = "processing"
        item.started_at = datetime.datetime.utcnow()
        db.commit()

        logger.info(f"[QueueWorker] Iniciando processamento do ativo {ticker} (ID Fila: {item.id})")

        try:
            # 1. Coleta de dados no ecossistema B3 (com Fallback e Trava de Segurança)
            dados, status_coleta = self.b3_engine.get_asset_data(ticker, db=db)

            now = datetime.datetime.utcnow()
            clean_ticker = ticker.upper().replace(".SA", "")

            # 2. Verifica se ativou a Trava de Segurança ("pausa_analise")
            if status_coleta == "pausa_analise":
                logger.warning(f"[QueueWorker] Trava ativada para {ticker}. Marcando como 'pausa_analise'.")
                
                # Atualiza ou cria Asset com pausa de análise
                asset = db.query(Asset).filter((Asset.ticker == ticker) | (Asset.ticker == clean_ticker)).first()
                if not asset:
                    asset = Asset(ticker=ticker, nome=clean_ticker)
                    db.add(asset)
                
                asset.status_analise = "pausa_analise"
                asset.conviccao = 0.0
                asset.validade_dias = 1
                asset.tese_resumida = "Bloqueio temporário de segurança: dados insuficientes ou falha em todas as fontes da B3."
                asset.fonte_dados = "Falha/Bloqueio"
                asset.data_autorizacao = now
                asset.data_expiracao = now + datetime.timedelta(days=1)
                asset.ultima_atualizacao = now
                save_analysis_run(db, clean_ticker, dados, status_coleta)
                db.commit()

                # Dispara Webhook de notificação com status pausa_analise
                decision_payload = TypeSafeDecisionFormatter.format_decision(
                    ticker=clean_ticker,
                    status="pausa_analise",
                    conviccao=0.0,
                    validade_dias=1,
                    tese_resumida=asset.tese_resumida,
                    indicadores={},
                    id_analise=item.id,
                    origem_decisao="Trava de segurança",
                    fontes_consultadas=dados.get("fonte_utilizada")
                )
                self.dispatcher.queue_decision(db, decision_payload)

                item.status = "completed"
                item.completed_at = now
                db.commit()
                return

            # 3. Recupera lições aprendidas anteriores (Settle-and-reflect)
            memorias = self.memory_engine.get_past_lessons(db, clean_ticker, limit=3)

            # 4. Cascata de Inteligência Artificial:
            # Etapa 1: Triagem de Notícias & Sentimento CVM
            triagem_meta: dict = {}
            triagem_texto = self.cascade.run_triage(
                db=db,
                ticker=clean_ticker,
                noticias=dados.get("noticias", []),
                cvm_info=dados.get("cvm", {}),
                meta=triagem_meta
            )

            # Etapa 2: Veredito Final pelo Agente Gestor
            decisao_meta: dict = {}
            veredito = self.cascade.run_manager_verdict(
                db=db,
                ticker=clean_ticker,
                dados_mercado=dados,
                triagem_sentimento=triagem_texto,
                memorias=memorias,
                meta=decisao_meta
            )

            status_decisao = veredito.get("status", "rejeitado").lower()
            conviccao = float(veredito.get("conviccao", 0.5))
            validade_dias = int(veredito.get("validade_dias", 7))
            tese_resumida = veredito.get("tese_resumida", "Análise executada com sucesso.")

            # 5. Atualiza o cadastro do Ativo no Cockpit
            asset = db.query(Asset).filter((Asset.ticker == ticker) | (Asset.ticker == clean_ticker)).first()
            if not asset:
                asset = Asset(ticker=ticker, nome=dados.get("nome", clean_ticker))
                db.add(asset)

            asset.nome = dados.get("nome", clean_ticker)
            asset.setor = dados.get("setor", "B3")
            asset.status_analise = status_decisao
            asset.conviccao = conviccao
            asset.validade_dias = validade_dias
            asset.tese_resumida = tese_resumida
            asset.indicadores = dados.get("indicadores", {})
            asset.fonte_dados = dados.get("fonte_utilizada", "B3")
            asset.data_autorizacao = now
            asset.data_expiracao = now + datetime.timedelta(days=validade_dias)
            asset.ultima_atualizacao = now
            save_analysis_run(db, clean_ticker, dados, status_coleta, triagem_texto=triagem_texto,
                              triagem_meta=triagem_meta, decisao_meta=decisao_meta, veredito=veredito)
            db.commit()

            # 6. Formata saída rígida TypeSafe e dispara Callback de Decisão via Webhook
            decision_payload = TypeSafeDecisionFormatter.format_decision(
                ticker=clean_ticker,
                status=status_decisao,
                conviccao=conviccao,
                validade_dias=validade_dias,
                tese_resumida=tese_resumida,
                indicadores=dados.get("indicadores", {}),
                id_analise=item.id,
                origem_decisao=decisao_meta.get("origem"),
                fontes_consultadas=dados.get("fonte_utilizada")
            )
            self.dispatcher.queue_decision(db, decision_payload)

            # 7. Finaliza item da fila
            item.status = "completed"
            item.completed_at = datetime.datetime.utcnow()
            db.commit()

            logger.info(f"[QueueWorker] Finalizado ativo {clean_ticker}: Status={status_decisao}, Convicção={conviccao}")

        except Exception as e:
            logger.error(f"[QueueWorker] Erro ao processar ativo {ticker}: {e}", exc_info=True)
            item.status = "failed"
            item.error_message = str(e)
            item.completed_at = datetime.datetime.utcnow()

            log = AuditLog(
                level="ERROR",
                category="QUEUE",
                message=f"Falha no processamento do ativo {ticker}: {str(e)}",
                details_json={"ticker": ticker, "queue_id": item.id}
            )
            db.add(log)
            db.commit()

    async def run_worker_loop(self):
        """Loop assíncrono de execução contínua"""
        self.is_running = True
        logger.info("[QueueWorker] Loop do worker em segundo plano iniciado.")
        while self.is_running:
            try:
                db = SessionLocal()
                try:
                    processed = self.process_next_batch(db)
                    # Também processa retentativas de webhooks pendentes
                    self.dispatcher.process_pending_retries(db)
                finally:
                    db.close()

                if processed == 0:
                    await asyncio.sleep(self.sleep_interval)
                else:
                    await asyncio.sleep(1.0) # Pequena pausa entre lotes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[QueueWorker] Erro no loop de execução: {e}")
                await asyncio.sleep(self.sleep_interval)

    def stop(self):
        self.is_running = False

_worker_instance = None

def get_queue_worker() -> QueueWorker:
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = QueueWorker()
    return _worker_instance
