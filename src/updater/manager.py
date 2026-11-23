"""
Atualização pelo próprio Cockpit.

Canal de atualização = uma PASTA (rede, OneDrive, Google Drive sincronizado, pendrive) ou uma URL
que contenha `latest.json`, gerado pelo script `build/build.py`:

    {"version": "8.1.0", "package": "TradingAgentsB3-app-8.1.0.zip",
     "sha256": "...", "size": 123456, "notes": "...", "published_at": "..."}

`package` pode ser um nome relativo ao latest.json ou uma URL completa.
"""
import datetime
import hashlib
import json
import shutil
import sqlite3
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import httpx
from sqlalchemy.orm import Session

from src.config import APP_VERSION, DATA_DIR, INSTALL_ROOT, UPDATE_CHANNEL, PORT, DATABASE_URL
from src.models import SystemSetting

UPDATES_DIR = DATA_DIR / "updates"
BACKUPS_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 10

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


class UpdateError(Exception):
    pass


def parse_version(v: str) -> Tuple[int, ...]:
    partes = []
    for p in str(v).strip().lstrip("v").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        partes.append(int(num) if num else 0)
    return tuple(partes + [0] * (3 - len(partes)))


def get_channel(db: Session) -> str:
    s = db.query(SystemSetting).filter(SystemSetting.key == "update_channel").first()
    return (s.value or "").strip() if s and s.value and s.value.strip() else UPDATE_CHANNEL.strip()


def _is_url(channel: str) -> bool:
    return channel.lower().startswith(("http://", "https://"))


def read_manifest(channel: str) -> Tuple[Dict[str, Any], str]:
    """Retorna (manifesto, local_base) onde local_base serve para resolver o pacote."""
    if not channel:
        raise UpdateError("Canal de atualização não configurado. Informe a pasta ou URL do latest.json.")
    if _is_url(channel):
        url = channel if channel.lower().endswith(".json") else channel.rstrip("/") + "/latest.json"
        try:
            r = httpx.get(url, timeout=20, follow_redirects=True)
            r.raise_for_status()
            return r.json(), url
        except Exception as e:
            raise UpdateError(f"Não foi possível ler {url}: {e}")
    p = Path(channel)
    manifest_path = p if p.suffix.lower() == ".json" else p / "latest.json"
    if not manifest_path.exists():
        raise UpdateError(f"Arquivo não encontrado: {manifest_path}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8-sig")), str(manifest_path)
    except Exception as e:
        raise UpdateError(f"latest.json inválido: {e}")


def installed_mode() -> bool:
    return INSTALL_ROOT is not None


def read_status() -> Dict[str, Any]:
    out: Dict[str, Any] = {"versao_instalada": APP_VERSION, "modo_instalado": installed_mode()}
    for nome, chave in (("status.json", "andamento"), ("last_result.json", "ultimo_resultado")):
        f = UPDATES_DIR / nome
        if f.exists():
            try:
                out[chave] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
    return out


def check(db: Session) -> Dict[str, Any]:
    channel = get_channel(db)
    manifest, _ = read_manifest(channel)
    disponivel = str(manifest.get("version", "")).strip()
    if not disponivel:
        raise UpdateError("latest.json sem o campo 'version'.")
    return {
        "canal": channel,
        "versao_instalada": APP_VERSION,
        "versao_disponivel": disponivel,
        "tem_atualizacao": parse_version(disponivel) > parse_version(APP_VERSION),
        "notas": manifest.get("notes") or "",
        "publicado_em": manifest.get("published_at"),
        "tamanho_bytes": manifest.get("size"),
        "modo_instalado": installed_mode(),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_package(db: Session) -> Path:
    channel = get_channel(db)
    manifest, base = read_manifest(channel)
    pkg = manifest.get("package")
    if not pkg:
        raise UpdateError("latest.json sem o campo 'package'.")
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    destino = UPDATES_DIR / f"pacote-{manifest.get('version', 'novo')}.zip"

    if _is_url(pkg) or _is_url(base):
        url = pkg if _is_url(pkg) else urljoin(base, pkg)
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                with open(destino, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        except Exception as e:
            raise UpdateError(f"Falha ao baixar o pacote: {e}")
    else:
        origem = Path(pkg) if Path(pkg).is_absolute() else Path(base).parent / pkg
        if not origem.exists():
            raise UpdateError(f"Pacote não encontrado: {origem}")
        shutil.copyfile(origem, destino)

    esperado = (manifest.get("sha256") or "").lower()
    if esperado and _sha256(destino) != esperado:
        destino.unlink(missing_ok=True)
        raise UpdateError("Pacote corrompido (SHA-256 não confere). Tente de novo.")
    return destino


def validate_package(zip_path: Path) -> str:
    """Confere a estrutura do pacote e devolve a versão dele."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            nomes = set(z.namelist())
            if z.testzip() is not None:
                raise UpdateError("Pacote corrompido.")
            for obrigatorio in ("VERSION", "main.py", "launcher.py"):
                if obrigatorio not in nomes:
                    raise UpdateError(f"Pacote inválido: falta '{obrigatorio}'. Use o .zip gerado por build/build.py.")
            if not any(n.startswith("src/") for n in nomes):
                raise UpdateError("Pacote inválido: falta a pasta 'src'.")
            return z.read("VERSION").decode("utf-8").strip()
    except zipfile.BadZipFile:
        raise UpdateError("O arquivo enviado não é um .zip válido.")


def backup_database(tag: str) -> Optional[Path]:
    """Cópia consistente do SQLite (API de backup) antes de trocar o código."""
    if not DATABASE_URL.startswith("sqlite:///"):
        return None
    db_path = Path(DATABASE_URL.replace("sqlite:///", "", 1))
    if not db_path.exists():
        return None
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    destino = BACKUPS_DIR / f"tradingagents-{tag}-{datetime.datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(destino))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    antigos = sorted(BACKUPS_DIR.glob("tradingagents-*.db"))[:-MAX_BACKUPS]
    for a in antigos:
        a.unlink(missing_ok=True)
    return destino


def launch_apply(zip_path: Path) -> Dict[str, Any]:
    """Faz backup e dispara o aplicador em processo separado (ele vai parar e reiniciar o servidor)."""
    if not installed_mode():
        raise UpdateError("A atualização automática só funciona na versão instalada pelo instalador "
                          "(aqui é o modo de desenvolvimento).")
    nova = validate_package(zip_path)
    if parse_version(nova) == parse_version(APP_VERSION):
        raise UpdateError(f"A versão {nova} já está instalada.")

    backup = backup_database(f"antes-{nova}")

    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    script = UPDATES_DIR / "apply_update.py"
    shutil.copyfile(Path(__file__).with_name("apply_update.py"), script)
    (UPDATES_DIR / "last_result.json").unlink(missing_ok=True)
    (UPDATES_DIR / "status.json").write_text(json.dumps(
        {"fase": "iniciando", "mensagem": f"Preparando atualização para {nova}...",
         "quando": datetime.datetime.now().isoformat()}, ensure_ascii=False), encoding="utf-8")

    import os
    python = INSTALL_ROOT / "runtime" / "python.exe"
    subprocess.Popen(
        [str(python), str(script), "--root", str(INSTALL_ROOT), "--data-dir", str(DATA_DIR),
         "--zip", str(zip_path), "--pid", str(os.getpid()), "--port", str(PORT)],
        cwd=str(INSTALL_ROOT),
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True,
    )
    return {"message": f"Atualização para {nova} iniciada. O sistema vai reiniciar em instantes.",
            "versao_nova": nova, "backup": str(backup) if backup else None}
