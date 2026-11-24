import sys
from pathlib import Path

# No Python embutido (versão instalada) a pasta do script não entra no sys.path sozinha
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import uvicorn
from src.config import HOST, PORT, DEBUG
from src.database import engine, Base, SessionLocal
from src.models import User
from src.auth.security import get_password_hash
from src.b3.data_engine import get_b3_data_engine
from src.queue.smart_queue import get_smart_queue
from src.watchdog.dual_watchdog import get_dual_watchdog

def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                hashed_password=get_password_hash("admin123"),
                is_active=True
            )
            db.add(admin)
            db.commit()
            print("[Init] Usuário admin criado com sucesso (admin / admin123)")
    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser(description="TradingAgents B3 & Cockpit Web (v8.0)")
    parser.add_argument("--serve", action="store_true", help="Inicia o servidor Cockpit Web e o Queue Worker")
    parser.add_argument("--port", type=int, default=PORT, help=f"Porta do servidor Web (padrão: {PORT})")
    parser.add_argument("--host", type=str, default=HOST, help=f"Host do servidor (padrão: {HOST})")
    parser.add_argument("--enqueue", type=str, help="Enfileira tickers para análise imediata (ex: PETR4,VALE3)")
    parser.add_argument("--watchdog", action="store_true", help="Executa checagem imediata dos Watchdogs")
    parser.add_argument("--mock-robot", action="store_true", help="Inicia o Robô Técnico Mock na porta 5000 para testes")
    parser.add_argument("--test-comms", action="store_true", help="Executa diagnóstico de comunicação com o Robô Técnico")
    
    args = parser.parse_args()

    if args.mock_robot:
        import mock_technical_robot
        mock_technical_robot.main()
        return

    if args.test_comms:
        import test_communication
        test_communication.run_tests()
        return

    init_db()


    if args.enqueue:
        tickers = [t.strip().upper() for t in args.enqueue.split(",") if t.strip()]
        db = SessionLocal()
        try:
            q = get_smart_queue()
            res = q.enqueue_assets(db, tickers, prioridade="alta", origem="cli_manual")
            print(f"[CLI] {res.total_enfileirados} ativos enfileirados: {res.ativos}")
        finally:
            db.close()
        return

    if args.watchdog:
        db = SessionLocal()
        try:
            wd = get_dual_watchdog()
            print("[Watchdog Upstream]:", wd.check_upstream(db))
            print("[Watchdog Custom]:", wd.check_custom_repo(db))
        finally:
            db.close()
        return

    # Padrão: Iniciar o Cockpit Web Server
    print("=" * 60)
    print("⚡ TradingAgents B3 & Cockpit Web (v8.0)")
    print("   Cérebro Estratégico Autorizador de Análise Fundamentalista")
    print(f"   Iniciando em: http://{args.host}:{args.port}")
    print("   Login padrão: admin / admin123")
    print("=" * 60)

    uvicorn.run(
        "src.web.app:app",
        host=args.host,
        port=args.port,
        reload=DEBUG,
        log_level="info"
    )

if __name__ == "__main__":
    main()
