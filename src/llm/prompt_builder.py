import json
from typing import Dict, Any, List

class PromptBuilder:
    """
    Construtor de Prompts Especializados para o Mercado Brasileiro (B3)
    com Injeção de Memória Histórica de Aprendizado (Post-Mortem).
    """

    @staticmethod
    def _format_news(noticias: List[Any]) -> str:
        if not noticias:
            return "Nenhuma notícia recente encontrada."
        linhas = []
        for n in noticias:
            if isinstance(n, dict):
                meta = ", ".join(x for x in (n.get("fonte"), n.get("data")) if x)
                linhas.append(f"- {n.get('titulo')}" + (f" ({meta})" if meta else ""))
            else:
                linhas.append(f"- {n}")
        return "\n".join(linhas)

    @staticmethod
    def _format_cvm(cvm_info: Dict[str, Any]) -> str:
        if not cvm_info:
            return "Sem dados da CVM nesta coleta."
        linhas = [
            f"Empresa: {cvm_info.get('empresa', '-')} | Segmento de listagem: {cvm_info.get('segmento_listagem') or '-'}",
            f"Documentos entregues nos últimos 45 dias: {cvm_info.get('qtd_documentos_45d', 0)} "
            f"(fatos relevantes: {cvm_info.get('qtd_fatos_relevantes_45d', 0)})",
        ]
        for d in cvm_info.get("documentos", []):
            linhas.append(f"- {d.get('data')}: {d.get('titulo')}")
        return "\n".join(linhas)

    @staticmethod
    def build_triage_prompt(ticker: str, noticias: List[Any], cvm_info: Dict[str, Any]) -> str:
        """Prompt para o modelo ágil/barato (Gemini Flash / DeepSeek) fazer triagem rápida"""
        news_text = PromptBuilder._format_news(noticias)
        cvm_text = PromptBuilder._format_cvm(cvm_info)

        return f"""Você é o Agente de Triagem Fundamentalista B3.
Sua função é avaliar com velocidade o sentimento das notícias e fatos relevantes para o ativo {ticker}.

[NOTÍCIAS RECENTES]:
{news_text}

[FATOS CVM / REGULATÓRIO]:
{cvm_text}

Analise em 3 linhas:
1. Sentimento predominante (Positivo, Neutro ou Negativo)
2. Fatos de risco ou oportunidades imediatas
3. Score preliminar de sentimento de 0.0 a 1.0.

Responda em formato conciso em Português do Brasil."""

    @staticmethod
    def build_manager_prompt(
        ticker: str,
        dados_mercado: Dict[str, Any],
        triagem_sentimento: str,
        memorias_passadas: List[Dict[str, Any]]
    ) -> str:
        """
        Prompt para o Agente Gestor (Modelo Avançado) emitir o veredito final.
        Injeta a tese fundamentalista e as Lições Aprendidas de trades anteriores (Settle-and-reflect).
        """
        indicadores = dados_mercado.get("indicadores", {})
        ind_text = json.dumps(indicadores, ensure_ascii=False, indent=2)

        macro = dados_mercado.get("macro") or {}
        if macro:
            macro_text = (f"- Selic meta: {macro.get('selic_meta_pct', '-')}% | "
                          f"IPCA 12m: {macro.get('ipca_12m_pct', '-')}% | "
                          f"Dólar PTAX: R$ {macro.get('dolar_ptax', '-')}")
        else:
            macro_text = "- Indisponível nesta coleta."

        avisos = dados_mercado.get("avisos") or []
        avisos_text = "\n".join(f"- {a}" for a in avisos) if avisos else "- Nenhum."
        fontes_text = dados_mercado.get("fonte_utilizada") or "-"

        # Injeção da Memória Pós-Morte
        if memorias_passadas:
            memory_section = "### [MEMÓRIA DE APRENDIZADO CONTÍNUO - LIÇÕES APRENDIDAS DE TRADES ANTERIORES]:\n"
            for idx, m in enumerate(memorias_passadas, 1):
                memory_section += (
                    f"{idx}. Resultado: {m.get('resultado')} | Motivo Gráfico: {m.get('motivo_grafico')}\n"
                    f"   Lição: {m.get('licao_aprendida')}\n"
                )
        else:
            memory_section = "### [MEMÓRIA DE APRENDIZADO CONTÍNUO]: Nenhum histórico de feedback anterior registrado para este ativo.\n"

        return f"""Você é o Agente Gestor Soberano de Análise Fundamentalista da B3 (TradingAgents Brasil).
Você atua como um "Cérebro Estratégico Autorizador" para um robô técnico externo.
Sua função é analisar a saúde fundamentalista do ativo {ticker}, avaliar riscos e decidir se a compra/operação é AUTORIZADA ou REJEITADA.

{memory_section}

### [INDICADORES FUNDAMENTALISTAS ATUAIS]:
- Preço Atual: R$ {dados_mercado.get('preco_atual', 0.0):.2f}
- Múltiplos:
{ind_text}

### [CONTEXTO MACROECONÔMICO (Banco Central)]:
{macro_text}

### [FONTES CONSULTADAS E QUALIDADE DOS DADOS]:
- Fontes que responderam: {fontes_text}
- Alertas de qualidade (dados descartados ou divergentes):
{avisos_text}

### [TRIAGEM DE NOTÍCIAS & SENTIMENTO]:
{triagem_sentimento}

### [DIRETRIZES DE DECISÃO]:
1. Leve em extrema consideração as Lições Aprendidas anteriores para não repetir erros passados neste mesmo ativo.
2. Defina o status estritamente como "autorizado" ou "rejeitado".
3. Forneça uma convicção de 0.00 a 1.00 (onde >= 0.70 é alta convicção).
4. Defina a validade da autorização em dias (padrão: 5 a 15 dias).
5. Escreva um resumo executivo claro e direto em Português (PT-BR).

### [FORMATO OBRIGATÓRIO DE RESPOSTA JSON]:
Responda ESTRITAMENTE em formato JSON puro, sem marcações markdown ao redor, seguindo o esquema:
{{
  "status": "autorizado",
  "conviccao": 0.85,
  "validade_dias": 7,
  "tese_resumida": "Resumo da tese em até 3 frases em Português",
  "pontos_fortes": ["ponto 1", "ponto 2"],
  "riscos_identificados": ["risco 1", "risco 2"]
}}"""

    @staticmethod
    def build_reflection_prompt(ticker: str, resultado: str, motivo_grafico: str, tese_original: str) -> str:
        """Prompt para a IA refletir sobre um trade encerrado (Settle-and-Reflect post-mortem)"""
        return f"""Você é o Agente de Reflexão Pós-Morte do TradingAgents B3.
O robô de análise técnica acaba de encerrar uma operação no ativo {ticker}.

[DADOS DA OPERAÇÃO]:
- Ativo: {ticker}
- Resultado: {resultado} (WIN = Lucro, LOSS = Prejuízo)
- Motivo Gráfico reportado pelo robô: {motivo_grafico}

[TESE FUNDAMENTALISTA QUE HAVIA SIDO APROVADA]:
{tese_original or 'Tese preliminar baseada em múltiplos operacionais.'}

Realize uma reflexão profunda (Post-Mortem):
1. Por que o resultado ocorreu à luz dos fundamentos da empresa?
2. Se foi LOSS: qual ponto cego fundamentalista a IA ignorou (ex: alavancagem alta, ruído político, sensibilidade a juros)?
3. Se foi WIN: o que confirmou a tese?
4. Sintetize em 2 frases a "Lição Aprendida" prática que deve ser consultada na próxima vez que este ativo for analisado.

Responda em JSON puro:
{{
  "licao_aprendida": "Texto da lição prática e objetiva...",
  "fator_chave": "Alavancagem / Sentimento / Rompimento falso / etc."
}}"""
