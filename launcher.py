"""
Launcher do TradingAgents B3 (usado pelos atalhos do Windows).

    pythonw launcher.py               -> garante o servidor rodando e abre o Cockpit no navegador
    pythonw launcher.py --background  -> garante o servidor rodando, sem abrir navegador (início com o Windows)
    python  launcher.py --stop        -> encerra o servidor

O servidor roda escondido (sem janela); a saída vai para <dados>\\logs\\server.log.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
INSTALLED = (ROOT / "runtime" / "python.exe").exists() and APP_DIR.name == "app"
DATA_DIR = Path(os.environ.get("TA_DATA_DIR") or (ROOT / "data" if INSTALLED else APP_DIR))

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def read_port() -> int:
    env = DATA_DIR / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("PORT="):
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    pass
    return 8001


PORT = read_port()
URL = f"http://127.0.0.1:{PORT}"


def health():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def start_server() -> bool:
    logs = DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "server.log"
    if log.exists() and log.stat().st_size > 5 * 1024 * 1024:  # rotação simples
        old = logs / "server.log.1"
        old.unlink(missing_ok=True)
        log.rename(old)

    pythonw = ROOT / "runtime" / "pythonw.exe" if INSTALLED else Path(sys.executable)
    env = dict(os.environ, TA_DATA_DIR=str(DATA_DIR), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    out = open(log, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [str(pythonw), str(APP_DIR / "main.py"), "--serve"],
        cwd=str(APP_DIR), env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW, close_fds=True,
    )
    (DATA_DIR / "server.pid").write_text(str(proc.pid))
    for _ in range(90):
        if health():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(1)
    return False


def stop_server():
    pid_file = DATA_DIR / "server.pid"
    if pid_file.exists():
        subprocess.run(["taskkill", "/PID", pid_file.read_text().strip(), "/F"],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
        pid_file.unlink(missing_ok=True)
    for _ in range(30):
        if not health():
            return
        time.sleep(0.5)


def alert(msg: str):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "TradingAgents B3", 0x10)
    except Exception:
        print(msg)


def process_alive(pid: int) -> bool:
    """Pergunta direto ao Windows (sem ler texto do tasklist: no Windows em português a saída vem em
    cp850 com acentos e quebrava a leitura como UTF-8, derrubando o reinício)."""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def log(msg: str):
    try:
        logs = DATA_DIR / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / "launcher.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def restart(pid: int):
    """Usado pelo Cockpit ao trocar porta/endereço: encerra o servidor atual e sobe lendo o .env de novo."""
    log(f"restart: encerrando PID {pid}; nova porta {PORT}")
    time.sleep(1.5)  # deixa o servidor responder ao clique
    r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)  # sem text=True: saída em cp850 no Windows PT-BR
    log(f"restart: taskkill -> código {r.returncode}")
    for _ in range(40):
        if not process_alive(pid):
            break
        time.sleep(0.5)
    ok = start_server()
    log(f"restart: servidor na porta {PORT} -> {'OK' if ok else 'FALHOU'}")
    if not ok:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--background", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--pid", type=int, default=0)
    a = ap.parse_args()

    if a.stop:
        stop_server()
        return

    if a.restart:
        restart(a.pid)
        return

    if not health() and not start_server():
        if not a.background:
            alert(f"O servidor não iniciou. Veja o log em:\n{DATA_DIR / 'logs' / 'server.log'}")
        sys.exit(1)

    if not a.background:
        webbrowser.open(URL)


if __name__ == "__main__":
    main()
