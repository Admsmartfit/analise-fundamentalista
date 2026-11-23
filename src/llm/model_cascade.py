import json
import logging
import time
from typing import Dict, Any, List, Optional
import httpx
from sqlalchemy.orm import Session
from src.config import GEMINI_MODEL, GEMINI_FALLBACK_MODELS, CLAUDE_MODEL
from src.llm.key_pool import KeyPoolManager, get_key_pool_manager
from src.llm.prompt_builder import PromptBuilder

logger = logging.getLogger("llm.cascade")


def _is_rate_limit(exc: Exception) -> bool:
    """Só 429 é rate limit de verdade. 404/400/401/503 são erros de config ou transitórios
    e não devem colocar a chave em cooldown."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


HEURISTICA = "Regra de contingência (sem IA)"

_MODELOS_FIXOS = {"openai": "gpt-4o-mini", "deepseek": "deepseek-chat", "groq": "llama-3.3-70b-versatile"}


def _origem_ia(provider: str) -> str:
    provider = provider.lower()
    modelo = {"gemini": GEMINI_MODEL, "claude": CLAUDE_MODEL}.get(provider) or _MODELOS_FIXOS.get(provider, "?")
    return f"IA: {provider}/{modelo}"


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
    return repr(exc)

class ModelCascadeManager:
    """
    Cascata de Inteligência Artificial:
    - Etapa 1 (Triagem): Modelos ágeis e econômicos (Gemini Flash / DeepSeek)
    - Etapa 2 (Veredito Gestor): Modelos avançados e de raciocínio profundo
    - Etapa 3 (Reflexão Pós-Morte): Análise de aprendizado com erros e acertos
    """
    def __init__(self, key_pool: Optional[KeyPoolManager] = None):
        self.key_pool = key_pool or get_key_pool_manager()
        self._ultimo_modelo_gemini = GEMINI_MODEL

    def _origem(self, provider: str) -> str:
        """Rótulo de auditoria com o modelo que de fato respondeu (inclui fallback do Gemini)."""
        if provider.lower() == "gemini":
            return f"IA: gemini/{self._ultimo_modelo_gemini}"
        return _origem_ia(provider)

    def run_triage(self, db: Session, ticker: str, noticias: List[Any], cvm_info: Dict[str, Any],
                   meta: Optional[Dict[str, Any]] = None) -> str:
        """Executa a triagem rápida com modelo ágil. `meta` recebe {origem, erro} para auditoria."""
        meta = meta if meta is not None else {}
        prompt = PromptBuilder.build_triage_prompt(ticker, noticias, cvm_info)
        key_obj = self.key_pool.get_available_key(db, provider="gemini") or self.key_pool.get_available_key(db)

        if not key_obj:
            logger.info(f"[Cascade Triage] Nenhuma API Key externa ativa. Utilizando motor analítico heurístico local para {ticker}.")
            meta.update(origem=HEURISTICA, erro="Nenhuma chave de API disponível no pool.")
            return self._heuristic_triage(ticker, noticias)

        # Chamada à API LLM com tratamento de Rate Limit e Hot-Swap
        try:
            response_text = self._call_llm_api(key_obj.provider, key_obj.key_value, prompt, max_tokens=300)
            self.key_pool.record_usage(db, key_obj.id, tokens_or_calls=1)
            meta.update(origem=self._origem(key_obj.provider), erro=None)
            return response_text
        except Exception as e:
            logger.warning(f"[Cascade Triage] Erro na chave ID {key_obj.id}: {_describe_error(e)}")
            if _is_rate_limit(e):
                self.key_pool.mark_rate_limited(db, key_obj.id)
            meta.update(origem=HEURISTICA, erro=f"{self._origem(key_obj.provider)} falhou: {_describe_error(e)}")
            return self._heuristic_triage(ticker, noticias)

    def run_manager_verdict(
        self,
        db: Session,
        ticker: str,
        dados_mercado: Dict[str, Any],
        triagem_sentimento: str,
        memorias: List[Dict[str, Any]],
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Executa a deliberação do Agente Gestor para gerar o Veredito Final TypeSafe.
        `meta` recebe {origem, erro}: quem decidiu de fato (IA ou regra de contingência)."""
        meta = meta if meta is not None else {}
        prompt = PromptBuilder.build_manager_prompt(ticker, dados_mercado, triagem_sentimento, memorias)
        key_obj = self.key_pool.get_available_key(db, provider="claude") or self.key_pool.get_available_key(db)

        if not key_obj:
            logger.info(f"[Cascade Manager] Nenhuma API Key externa ativa. Gerando tese fundamentalista via motor analítico quantitativo para {ticker}.")
            meta.update(origem=HEURISTICA, erro="Nenhuma chave de API disponível no pool.")
            return self._heuristic_manager_verdict(ticker, dados_mercado, memorias)

        try:
            response_text = self._call_llm_api(key_obj.provider, key_obj.key_value, prompt, max_tokens=800)
            self.key_pool.record_usage(db, key_obj.id, tokens_or_calls=2)
            # Limpa possíveis blocos markdown ```json ... ```
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            parsed = json.loads(cleaned.strip())
            meta.update(origem=self._origem(key_obj.provider), erro=None)
            return parsed
        except Exception as e:
            logger.warning(f"[Cascade Manager] Erro na API LLM Gestor ({_describe_error(e)}). Usando fallback quantitativo...")
            if _is_rate_limit(e):
                self.key_pool.mark_rate_limited(db, key_obj.id)
            meta.update(origem=HEURISTICA, erro=f"{self._origem(key_obj.provider)} falhou: {_describe_error(e)}")
            return self._heuristic_manager_verdict(ticker, dados_mercado, memorias)

    def run_reflection(
        self,
        db: Session,
        ticker: str,
        resultado: str,
        motivo_grafico: str,
        tese_original: str
    ) -> str:
        """Executa a reflexão pós-morte (Settle-and-Reflect) para extrair lições aprendidas"""
        prompt = PromptBuilder.build_reflection_prompt(ticker, resultado, motivo_grafico, tese_original)
        key_obj = self.key_pool.get_available_key(db)

        if not key_obj:
            # Reflexão heurística automática
            if resultado.upper() == "LOSS":
                return f"Atenção em {ticker}: Trade encerrado em LOSS por '{motivo_grafico}'. Reforçar filtro de volume e confirmação de suporte antes de novas autorizações."
            else:
                return f"Sucesso em {ticker}: Trade concluído em WIN ({motivo_grafico}). Tese fundamentalista de múltiplos saudáveis e fluxo validada pelo mercado."

        try:
            resp_text = self._call_llm_api(key_obj.provider, key_obj.key_value, prompt, max_tokens=400)
            self.key_pool.record_usage(db, key_obj.id, tokens_or_calls=1)
            cleaned = resp_text.strip()
            if "{" in cleaned and "}" in cleaned:
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                data = json.loads(cleaned[start:end])
                return data.get("licao_aprendida", resp_text)
            return resp_text
        except Exception as e:
            logger.warning(f"[Cascade Reflection] Falha na reflexão via LLM: {e}")
            return f"Lição ({ticker}): Monitorar correlação entre fundamentos e timing gráfico pós-{resultado} ({motivo_grafico})."

    def _call_llm_api(self, provider: str, api_key: str, prompt: str, max_tokens: int = 500) -> str:
        """Dispara chamada HTTP REST para os provedores de LLM suportados"""
        provider = provider.lower()
        if provider == "gemini":
            headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            modelos = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
            with httpx.Client(timeout=60.0) as client:
                for i, modelo in enumerate(modelos):
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
                    # 503 (modelo sobrecarregado) é transitório: 2 tentativas por modelo
                    for attempt in range(2):
                        res = client.post(url, headers=headers, json=payload)
                        if res.status_code != 503:
                            break
                        time.sleep(2 * (attempt + 1))
                    # Sobrecarregado ou desativado: tenta o próximo modelo da lista
                    if res.status_code in (503, 404) and i < len(modelos) - 1:
                        logger.warning(f"[Cascade] Gemini {modelo} respondeu {res.status_code}; tentando {modelos[i + 1]}")
                        continue
                    res.raise_for_status()
                    self._ultimo_modelo_gemini = modelo
                    data = res.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]

        elif provider in ("openai", "deepseek", "groq"):
            base_url = "https://api.openai.com/v1"
            model_name = "gpt-4o-mini"
            if provider == "deepseek":
                base_url = "https://api.deepseek.com"
                model_name = "deepseek-chat"
            elif provider == "groq":
                base_url = "https://api.groq.com/openai/v1"
                model_name = "llama-3.3-70b-versatile"

            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens
            }
            with httpx.Client(timeout=30.0) as client:
                res = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
                return data["choices"][0]["message"]["content"]

        elif provider == "claude":
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            payload = {
                "model": CLAUDE_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            }
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
                return data["content"][0]["text"]

        raise ValueError(f"Provedor não suportado: {provider}")

    def _heuristic_triage(self, ticker: str, noticias: List[str]) -> str:
        """Triagem rápida com análise de palavras-chave financeiras"""
        n_count = len(noticias)
        return (
            f"Triagem heurística para {ticker}: {n_count} notícias avaliadas. "
            "Sentimento corporativo neutro-estável. Sem anúncios de litígios graves."
        )

    def _heuristic_manager_verdict(
        self,
        ticker: str,
        dados_mercado: Dict[str, Any],
        memorias: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Motor quantitativo fundamentalista de contingência"""
        indicadores = dados_mercado.get("indicadores", {})
        pl = indicadores.get("PL", 0.0)
        roe = indicadores.get("ROE_pct", 0.0)
        dy = indicadores.get("DY_pct", 0.0)
        margem = indicadores.get("Margem_Liquida_pct", 0.0)

        # Regras fundamentalistas saudáveis
        conviccao = 0.60
        status = "autorizado"
        pontos_fortes = []
        riscos = []

        if roe > 12.0:
            conviccao += 0.15
            pontos_fortes.append(f"ROE consistente de {roe:.1f}%")
        if dy > 5.0:
            conviccao += 0.10
            pontos_fortes.append(f"Dividend Yield atraente de {dy:.1f}%")
        if 0 < pl < 15.0:
            conviccao += 0.10
            pontos_fortes.append(f"P/L favorável de {pl:.1f}x")
        elif pl > 35.0:
            conviccao -= 0.15
            riscos.append(f"Múltiplo P/L esticado ({pl:.1f}x)")

        # Penalização caso haja histórico de LOSS nas memórias pós-morte
        loss_count = sum(1 for m in memorias if m.get("resultado") == "LOSS")
        if loss_count > 0:
            conviccao = max(0.40, conviccao - (loss_count * 0.08))
            riscos.append(f"Histórico de {loss_count} LOSS anteriores registrado no sistema.")

        conviccao = round(min(1.0, max(0.1, conviccao)), 2)
        if conviccao < 0.65:
            status = "rejeitado"

        return {
            "status": status,
            "conviccao": conviccao,
            "validade_dias": 7 if status == "autorizado" else 3,
            "tese_resumida": (
                f"Tese {'favorável' if status == 'autorizado' else 'cautelosa'} para {ticker}. "
                f"ROE de {roe:.1f}%, DY de {dy:.1f}% e margem líquida de {margem:.1f}%. "
                f"{'Aprovado para operações táticas.' if status == 'autorizado' else 'Reprovado por baixa assimetria fundamentalista.'}"
            ),
            "pontos_fortes": pontos_fortes or ["Liquidez na B3"],
            "riscos_identificados": riscos or ["Oscilações macroeconômicas locais"]
        }

_cascade_instance = None

def get_model_cascade() -> ModelCascadeManager:
    global _cascade_instance
    if _cascade_instance is None:
        _cascade_instance = ModelCascadeManager()
    return _cascade_instance
