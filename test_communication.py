#!/usr/bin/env python3
"""
Script de Teste Automatizado de Comunicação (TradingAgents B3 <-> Robô Técnico)
Executa diagnóstico completo da conectividade bidirecional na mesma máquina.
"""

import sys
import time
import json
import httpx

TRADINGAGENTS_URL = "http://127.0.0.1:8001"
ROBOT_WEBHOOK_URL = "http://127.0.0.1:5000/webhook/decisao"

def run_tests():
    print("=" * 65)
    print("🧪 DIAGNÓSTICO DE COMUNICAÇÃO: TRADINGAGENTS <-> ROBÔ TÉCNICO")
    print("=" * 65)

    # 1. Teste de Conexão com o TradingAgents
    print("\n[1/5] Verificando se o TradingAgents está ativo em http://127.0.0.1:8001...")
    ta_online = False
    try:
        with httpx.Client(timeout=3.0) as client:
            r = client.get(f"{TRADINGAGENTS_URL}/api/auth/me")
            # 401 significa que o servidor está online e respondendo (exige token)
            if r.status_code in (200, 401):
                print("  ✔ TradingAgents está ONLINE e respondendo na porta 8001.")
                ta_online = True
            else:
                print(f"  ✔ TradingAgents respondeu com HTTP {r.status_code}.")
                ta_online = True
    except Exception as e:
        print(f"  ✖ Falha ao conectar no TradingAgents ({e}).")
        print("    Dica: Inicie o TradingAgents em outro terminal com: python main.py")

    # 2. Teste de Conexão com o Robô Técnico
    print(f"\n[2/5] Verificando se o Robô Técnico está ativo em {ROBOT_WEBHOOK_URL}...")
    robot_online = False
    try:
        with httpx.Client(timeout=3.0) as client:
            # Envia ping de teste direto
            payload = {
                "tipo": "ping_teste",
                "origem": "test_communication.py",
                "mensagem": "Ping de teste direto",
                "timestamp": time.time()
            }
            r = client.post(ROBOT_WEBHOOK_URL, json=payload)
            if r.status_code in (200, 201, 202, 204):
                print(f"  ✔ Robô Técnico está ONLINE e respondeu com HTTP {r.status_code}.")
                print(f"    Resposta: {r.text[:150]}")
                robot_online = True
            else:
                print(f"  ✖ Robô Técnico respondeu com código inesperado: HTTP {r.status_code}")
    except httpx.ConnectError:
        print(f"  ✖ Conexão recusada na porta 5000 ({ROBOT_WEBHOOK_URL}).")
        print("    Dica: Inicie o Robô Técnico (ou o simulador mock) com: python mock_technical_robot.py")
    except Exception as e:
        print(f"  ✖ Erro ao contactar o Robô Técnico: {e}")

    # 3. Teste do Ping de TradingAgents -> Robô Técnico
    if ta_online:
        print("\n[3/5] Testando chamada TradingAgents -> Robô Técnico via endpoint de Ping...")
        try:
            with httpx.Client(timeout=5.0) as client:
                # Faz login de admin no TradingAgents para obter token
                login_res = client.post(f"{TRADINGAGENTS_URL}/api/auth/login", json={"username": "admin", "password": "admin123"})
                if login_res.status_code == 200:
                    token = login_res.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    ping_res = client.post(
                        f"{TRADINGAGENTS_URL}/api/webhooks/test-ping",
                        headers=headers,
                        json={"target_url": ROBOT_WEBHOOK_URL}
                    )
                    data = ping_res.json()
                    if data.get("ok"):
                        print(f"  ✔ TradingAgents conectou no Robô Técnico com sucesso! Latência: {data.get('latency_ms')} ms")
                    else:
                        print(f"  ✖ TradingAgents não conseguiu alcançar o Robô Técnico: {data.get('erro')}")
                else:
                    print("  ✖ Não foi possível autenticar no TradingAgents para testar o ping.")
        except Exception as e:
            print(f"  ✖ Falha no teste de ping integrado: {e}")
    else:
        print("\n[3/5] Pulando teste de ping integrado (TradingAgents offline).")

    # 4. Teste de Demanda (Robô -> TradingAgents)
    if ta_online:
        print("\n[4/5] Testando envio de demanda de ativos (Robô -> TradingAgents)...")
        try:
            with httpx.Client(timeout=5.0) as client:
                demand_payload = {
                    "ativos": ["PETR4", "VALE3"],
                    "prioridade": "normal",
                    "origem": "teste_comunicacao_script"
                }
                r = client.post(f"{TRADINGAGENTS_URL}/api/queue/demand", json=demand_payload)
                if r.status_code == 200:
                    data = r.json()
                    print(f"  ✔ Demanda aceita em milissegundos com HTTP 200:")
                    print(f"    Status: {data.get('status')} | Ativos: {data.get('ativos')} | Total: {data.get('total_enfileirados')}")
                else:
                    print(f"  ✖ Demanda rejeitada com HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ✖ Falha ao enviar demanda: {e}")

    # 5. Teste de Feedback de Trade (Settle-and-Reflect)
    if ta_online:
        print("\n[5/5] Testando envio de feedback de trade (WIN/LOSS) para Settle-and-Reflect...")
        try:
            with httpx.Client(timeout=10.0) as client:
                fb_payload = {
                    "ativo": "PETR4",
                    "resultado": "WIN",
                    "motivo_grafico": "Alvo de 3% atingido em rompimento de pivô",
                    "lucro_prejuizo_pct": 3.0
                }
                r = client.post(f"{TRADINGAGENTS_URL}/api/memory/feedback", json=fb_payload)
                if r.status_code == 200:
                    data = r.json()
                    print(f"  ✔ Feedback recebido e Reflexão Pós-Morte gravada com sucesso:")
                    print(f"    Ativo: {data.get('ticker')} | Resultado: {data.get('resultado')}")
                    print(f"    Lição Aprendida: {data.get('licao_aprendida')}")
                else:
                    print(f"  ✖ Feedback rejeitado com HTTP {r.status_code}: {r.text}")
        except Exception as e:
            print(f"  ✖ Falha ao enviar feedback: {e}")

    print("\n" + "=" * 65)
    print("📋 RESUMO FINAL DO DIAGNÓSTICO:")
    print(f"  - TradingAgents (Porta 8001): {'ONLINE ✔' if ta_online else 'OFFLINE ✖'}")
    print(f"  - Robô Técnico  (Porta 5000): {'ONLINE ✔' if robot_online else 'OFFLINE ✖'}")
    if ta_online and robot_online:
        print("  🎉 COMUNICAÇÃO BIDIRECIONAL COMPLETA E FUNCIONANDO!")
    elif not ta_online:
        print("  👉 Inicie o TradingAgents: python main.py")
    elif not robot_online:
        print("  👉 Inicie o Robô Técnico: python mock_technical_robot.py")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    run_tests()
