#!/usr/bin/env python3
"""
Robô Técnico Mock (Simulador de Comunicação Bidirecional)
Executa na mesma máquina (por padrão na porta 5000) e simula o robô de análise técnica externa.

Capacidades:
1. Recebe os Webhooks de Decisão do TradingAgents em `POST /webhook/decisao` (Porta 5000)
2. Responde aos pings de teste de conexão com `HTTP 200`
3. Dispara demandas de ativos para o TradingAgents (`POST http://127.0.0.1:8001/api/queue/demand`)
4. Dispara feedback de trades (WIN/LOSS) para o Settle-and-Reflect (`POST http://127.0.0.1:8001/api/memory/feedback`)
"""

import sys
import json
import argparse
import datetime
from typing import Dict, Any, List, Optional
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Robô Técnico (Mock de Teste)", version="1.0.0")

# Histórico em memória de decisões recebidas do TradingAgents
recebidos: List[Dict[str, Any]] = []
TRADINGAGENTS_BASE_URL = "http://127.0.0.1:8001"

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "Robô de Análise Técnica (Mock de Teste)",
        "porta": 5000,
        "endpoint_webhook": "http://127.0.0.1:5000/webhook/decisao",
        "total_webhooks_recebidos": len(recebidos)
    }

@app.post("/webhook/decisao")
async def receber_decisao(request: Request):
    """
    Endpoint que recebe os callbacks de decisão e pings de teste do TradingAgents.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    agora = datetime.datetime.now().strftime("%H:%M:%S")

    # 1. Caso seja um Ping de Teste
    if payload.get("tipo") == "ping_teste":
        print(f"\n⚡ [{agora}] [PING DE TESTE RECEBIDO DO TRADINGAGENTS]")
        print(f"   Mensagem: {payload.get('mensagem')}")
        print(f"   Origem: {payload.get('origem')}")
        return JSONResponse(status_code=200, content={
            "status": "sucesso",
            "recebido": True,
            "tipo": "pong_teste",
            "mensagem": "Robô Técnico recebeu o teste com sucesso!",
            "horario": agora
        })

    # 2. Caso seja um Callback de Decisão Fundamentalista (TypeSafe)
    ativo = payload.get("ativo", "INDEFINIDO")
    status_decisao = payload.get("status", "desconhecido").upper()
    conviccao = payload.get("conviccao", 0.0)
    validade = payload.get("validade_dias", 0)
    tese = payload.get("tese_resumida", "")

    registro = {
        "horario": agora,
        "ativo": ativo,
        "status": status_decisao,
        "conviccao": conviccao,
        "validade_dias": validade,
        "tese": tese,
        "payload_completo": payload
    }
    recebidos.append(registro)

    print("\n" + "=" * 65)
    print(f"📥 [{agora}] DECISÃO FUNDAMENTALISTA RECEBIDA DO TRADINGAGENTS:")
    print(f"   Ativo:          {ativo}")
    print(f"   Status:         {status_decisao}")
    print(f"   Convicção:      {round(conviccao * 100)}%")
    print(f"   Validade:       {validade} dias")
    print(f"   Tese Executiva: {tese}")
    if payload.get("indicadores_chave"):
        print(f"   Indicadores:    {json.dumps(payload.get('indicadores_chave'), ensure_ascii=False)}")
    print("=" * 65 + "\n")

    return JSONResponse(status_code=200, content={
        "status": "sucesso",
        "recebido": True,
        "ativo": ativo,
        "decisao_processada": status_decisao,
        "horario": agora
    })

@app.get("/decisoes")
def listar_decisoes():
    """Retorna histórico de decisões recebidas nesta sessão"""
    return {"total": len(recebidos), "decisoes": recebidos}

def enviar_demanda_teste(tickers: List[str], prioridade: str = "normal", base_url: str = TRADINGAGENTS_BASE_URL):
    """Dispara demanda de reavaliação para o TradingAgents"""
    url = f"{base_url.rstrip('/')}/api/queue/demand"
    payload = {
        "ativos": tickers,
        "prioridade": prioridade,
        "origem": "robo_tecnico_mock"
    }
    print(f"\n📤 Enviando demanda de {len(tickers)} ativos para o TradingAgents ({url})...")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                print(f"✔ Resposta imediata do TradingAgents (HTTP {resp.status_code}):")
                print(f"  {json.dumps(resp.json(), indent=2, ensure_ascii=False)}")
            else:
                print(f"✖ Erro ao enviar demanda (HTTP {resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"✖ Falha de conexão com TradingAgents: {e}")

def enviar_feedback_trade(ticker: str, resultado: str, motivo: str, lucro_pct: float = 0.0, base_url: str = TRADINGAGENTS_BASE_URL):
    """Dispara encerramento de trade (WIN/LOSS) para o TradingAgents refletir (Settle-and-Reflect)"""
    url = f"{base_url.rstrip('/')}/api/memory/feedback"
    payload = {
        "ativo": ticker,
        "resultado": resultado.upper(),
        "motivo_grafico": motivo,
        "lucro_prejuizo_pct": lucro_pct
    }
    print(f"\n📤 Enviando feedback de trade ({ticker}: {resultado}) para o TradingAgents...")
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                print(f"✔ Reflexão Pós-Morte concluída pelo TradingAgents:")
                print(f"  Lição Aprendida gravada: {data.get('licao_aprendida')}")
            else:
                print(f"✖ Erro ao enviar feedback (HTTP {resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"✖ Falha de conexão com TradingAgents: {e}")

def main():
    parser = argparse.ArgumentParser(description="Robô Técnico Mock para Testes de Comunicação")
    parser.add_argument("--port", type=int, default=5000, help="Porta onde o Robô Técnico escuta (padrão: 5000)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host (padrão: 127.0.0.1)")
    parser.add_argument("--send-demand", type=str, help="Envia demanda para TradingAgents e encerra (ex: PETR4,VALE3)")
    parser.add_argument("--send-feedback", nargs=3, metavar=("TICKER", "RESULTADO", "MOTIVO"), help="Envia feedback (ex: VALE3 LOSS 'Rompimento falso')")
    parser.add_argument("--tradingagents-url", type=str, default=TRADINGAGENTS_BASE_URL, help="URL base do TradingAgents")
    args = parser.parse_args()

    if args.send_demand:
        tickers = [t.strip().upper() for t in args.send_demand.split(",") if t.strip()]
        enviar_demanda_teste(tickers, base_url=args.tradingagents_url)
        return

    if args.send_feedback:
        ticker, res, motivo = args.send_feedback
        enviar_feedback_trade(ticker, res, motivo, base_url=args.tradingagents_url)
        return

    print("=" * 65)
    print("🤖 Robô Técnico (Mock de Teste) - Ouvindo na Porta", args.port)
    print(f"   Webhook de Destino: http://127.0.0.1:{args.port}/webhook/decisao")
    print(f"   TradingAgents Alvo: {args.tradingagents_url}")
    print("=" * 65)
    print("Pronto para receber decisões e testes do TradingAgents!")
    print("Para disparar ações de teste por este script em outro terminal:")
    print("  python mock_technical_robot.py --send-demand PETR4,VALE3")
    print("  python mock_technical_robot.py --send-feedback VALE3 LOSS 'Rompimento falso'")
    print("=" * 65 + "\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
