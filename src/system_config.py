"""
Porta e endereço do Cérebro, configuráveis pelo Cockpit.

Grava HOST/PORT no .env da pasta de dados (mantendo as demais linhas) e, na versão instalada,
reinicia o servidor sozinho pelo launcher, que sobe já na porta nova.
"""
import os
import socket
import subprocess
from pathlib import Path
from typing import Dict

from src.config import DATA_DIR, INSTALL_ROOT, HOST, PORT

HOSTS_VALIDOS = {
    "127.0.0.1": "Somente este computador (recomendado)",
    "0.0.0.0": "Este computador e outros da rede (exige liberar no firewall)",
}

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def env_path() -> Path:
    return DATA_DIR / ".env"


def read_env(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def set_env_values(path: Path, updates: Dict[str, str]) -> None:
    """Troca/insere chaves no .env sem mexer no resto (comentários, segredos)."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    pendentes = dict(updates)
    novas = []
    for line in lines:
        s = line.strip()
        chave = s.split("=", 1)[0].strip() if "=" in s and not s.startswith("#") else None
        if chave in pendentes:
            novas.append(f"{chave}={pendentes.pop(chave)}")
        else:
            novas.append(line)
    novas += [f"{k}={v}" for k, v in pendentes.items()]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(novas) + "\n", encoding="utf-8")
    tmp.replace(path)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def current() -> Dict[str, object]:
    salvo = read_env(env_path())
    return {
        "host_em_uso": HOST,
        "porta_em_uso": PORT,
        "host_salvo": salvo.get("HOST", HOST),
        "porta_salva": int(salvo.get("PORT", PORT)) if str(salvo.get("PORT", PORT)).isdigit() else PORT,
        "url": f"http://127.0.0.1:{PORT}",
        "hosts": HOSTS_VALIDOS,
        "modo_instalado": INSTALL_ROOT is not None,
        "arquivo": str(env_path()),
    }


def schedule_restart() -> None:
    """Pede ao launcher (processo separado) para encerrar este servidor e subir de novo lendo o .env."""
    python = INSTALL_ROOT / "runtime" / "python.exe"
    launcher = INSTALL_ROOT / "app" / "launcher.py"
    env = dict(os.environ, TA_DATA_DIR=str(DATA_DIR), PYTHONIOENCODING="utf-8")
    logs = DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    err = open(logs / "launcher.log", "a", encoding="utf-8")  # erros do launcher não somem (ele roda sem janela)
    subprocess.Popen(
        [str(python), str(launcher), "--restart", "--pid", str(os.getpid())],
        cwd=str(INSTALL_ROOT), env=env, stdin=subprocess.DEVNULL, stdout=err, stderr=err,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW, close_fds=True,
    )
