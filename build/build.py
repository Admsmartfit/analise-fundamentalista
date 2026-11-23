"""
Gera o instalador único para Windows e o pacote de atualização.

Uso (na pasta do projeto):
    python build/build.py                                  # gera tudo em dist/
    python build/build.py --notes "O que mudou"            # notas exibidas no botão Atualizar
    python build/build.py --channel "G:\\Meu Drive\\TA-updates"  # canal já configurado no instalador
    python build/build.py --publish "G:\\Meu Drive\\TA-updates"  # copia pacote + latest.json para o canal
    python build/build.py --include-db                     # leva o banco atual (chaves, ativos, histórico)

Saída em dist/:
    TradingAgentsB3-Setup-X.Y.Z.exe   instalador único (Python embutido + dependências + sistema)
    TradingAgentsB3-app-X.Y.Z.zip     pacote de atualização (só o código)
    latest.json                       manifesto lido pelo botão "Atualizar"

Para lançar uma versão nova: aumente o número em VERSION, rode com --publish e clique em
"Verificar" / "Atualizar" no Cockpit da máquina instalada.
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CACHE = BUILD / "cache"
DIST = ROOT / "dist"
INSTALLER_SRC = ROOT / "installer"

APP_FILES = ["main.py", "launcher.py", "VERSION", "requirements.txt", "README.md", ".env.example"]
APP_DIRS = ["src", "docs"]
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}

# Módulos que precisam importar no Python embutido (inclui dependências implícitas como lxml)
SMOKE_IMPORTS = ("fastapi, uvicorn, yfinance, sqlalchemy, bs4, lxml, httpx, jose, bcrypt, apscheduler, "
                 "dotenv, jinja2, multipart, pydantic, requests, pip")


def log(msg):
    print(f"[build] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        raise SystemExit(f"Falhou: {' '.join(map(str, cmd))[:200]}")
    return r


# ---------------------------------------------------------------- runtime
def build_runtime() -> Path:
    v = sys.version_info
    if os.name != "nt" or sys.maxsize <= 2**32:
        raise SystemExit("Rode o build num Windows com Python 64 bits.")
    pyver = f"{v.major}.{v.minor}.{v.micro}"
    req_hash = sha256(ROOT / "requirements.txt")[:12]
    rt = CACHE / f"runtime-{pyver}-{req_hash}"
    if (rt / ".ok").exists():
        log(f"Runtime em cache: {rt.name}")
        return rt

    CACHE.mkdir(parents=True, exist_ok=True)
    embed = CACHE / f"python-{pyver}-embed-amd64.zip"
    if not embed.exists():
        url = f"https://www.python.org/ftp/python/{pyver}/python-{pyver}-embed-amd64.zip"
        log(f"Baixando Python embutido {pyver}...")
        urllib.request.urlretrieve(url, embed)

    tmp = CACHE / f"_runtime_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(embed) as z:
        z.extractall(tmp)

    # Habilita site-packages no Python embutido
    pth = next(tmp.glob("python*._pth"))
    zipname = f"python{v.major}{v.minor}.zip"
    pth.write_text(f"{zipname}\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")
    site = tmp / "Lib" / "site-packages"
    site.mkdir(parents=True)

    log("Instalando dependências no runtime (alguns minutos na 1ª vez)...")
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
         "--target", str(site), "-r", str(ROOT / "requirements.txt"), "pip"])

    log("Testando imports no runtime...")
    run([str(tmp / "python.exe"), "-c", f"import {SMOKE_IMPORTS}; print('ok')"])

    shutil.rmtree(rt, ignore_errors=True)
    tmp.rename(rt)
    (rt / ".ok").write_text(pyver)
    return rt


# ---------------------------------------------------------------- app
def stage_app(dst: Path):
    shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True)
    for f in APP_FILES:
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, dst / f)
    for d in APP_DIRS:
        for path in (ROOT / d).rglob("*"):
            rel = path.relative_to(ROOT)
            if any(p in SKIP_DIRS for p in rel.parts) or path.suffix in SKIP_SUFFIX:
                continue
            target = dst / rel
            if path.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)


def smoke_test_app(runtime: Path, app_dir: Path):
    log("Testando o sistema com o runtime embutido...")
    with tempfile.TemporaryDirectory() as data:
        env = dict(os.environ, TESTING="1", TA_DATA_DIR=data, PYTHONIOENCODING="utf-8")
        env.pop("PYTHONPATH", None)
        code = ("import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).parent))\n"
                "import src.web.app\n"
                "from src.sources.news import parse_rss\n"
                "assert parse_rss(b'<rss><channel><item><title>x</title></item></channel></rss>', 't')[0]['titulo'] == 'x'\n"
                "from fastapi.testclient import TestClient\n"
                "from src.web.app import app\n"
                "c = TestClient(app)\n"
                "for url in ('/', '/login', '/api/health', '/static/js/app.js'):\n"
                "    r = c.get(url); assert r.status_code == 200, (url, r.status_code, r.text[:300])\n"
                "from src.config import APP_VERSION; print('ok', APP_VERSION)\n")
        smoke = app_dir / "_smoke_test.py"
        smoke.write_text(code, encoding="utf-8")
        try:
            r = run([str(runtime / "python.exe"), str(smoke)], cwd=str(app_dir), env=env)
        finally:
            smoke.unlink(missing_ok=True)
        log(r.stdout.strip().splitlines()[-1])


def run_tests_in_runtime(runtime: Path):
    """Roda a suíte de testes com as MESMAS bibliotecas que vão no instalador."""
    log("Rodando os testes dentro do Python embutido...")
    pytest_dir = CACHE / "pytest-target"
    if not (pytest_dir / "pytest").exists():
        run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
             "--target", str(pytest_dir), "pytest"])
    script = ("import sys, os\n"
              f"sys.path[0:0] = [{str(pytest_dir)!r}, {str(ROOT)!r}]\n"
              f"os.chdir({str(ROOT)!r})\n"
              "import pytest\n"
              "sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', '-p', 'no:warnings', 'tests']))\n")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "run_tests.py"
        f.write_text(script, encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", TA_DATA_DIR=tmp)
        r = run([str(runtime / "python.exe"), str(f)], env=env)
    log(r.stdout.strip().splitlines()[-1])


def zip_dir(src: Path, zip_path: Path, prefix: str = "", level: int = 6):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as z:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                z.write(path, (prefix + path.relative_to(src).as_posix()))


# ---------------------------------------------------------------- ícone
def make_icon(dst: Path) -> bool:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 248, 248), radius=56, fill=(21, 25, 33, 255), outline=(59, 130, 246, 255), width=10)
    d.polygon([(150, 30), (70, 140), (124, 140), (100, 226), (186, 110), (132, 110)], fill=(245, 158, 11, 255))
    img.save(dst, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return True


# ---------------------------------------------------------------- instalador
SED = """[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=TradingAgents B3 {version}
AppLaunched=cmd /c setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="setup.cmd"
FILE1="install.ps1"
FILE2="payload.zip"
[SourceFiles]
SourceFiles0={src}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"""


def build_installer(runtime: Path, app_dir: Path, version: str, channel: str, include_db: bool) -> Path:
    # IExpress não lida bem com espaços no caminho: trabalha numa pasta temporária sem espaços
    work = Path(tempfile.gettempdir()) / "ta_b3_build"
    shutil.rmtree(work, ignore_errors=True)
    payload_dir = work / "payload"
    pkg_dir = work / "pkg"
    payload_dir.mkdir(parents=True)
    pkg_dir.mkdir()

    log("Montando payload (runtime + app)...")
    shutil.copytree(runtime, payload_dir / "runtime", ignore=shutil.ignore_patterns(".ok", "__pycache__"))
    shutil.copytree(app_dir, payload_dir / "app")
    shutil.copy2(INSTALLER_SRC / "uninstall.ps1", payload_dir / "uninstall.ps1")
    if make_icon(payload_dir / "TradingAgents.ico"):
        log("Ícone gerado.")
    if channel:
        (payload_dir / "channel.txt").write_text(channel, encoding="utf-8")
    if include_db:
        db = ROOT / "tradingagents.db"
        if db.exists():
            (payload_dir / "seed").mkdir()
            import sqlite3
            src, dst = sqlite3.connect(str(db)), sqlite3.connect(str(payload_dir / "seed" / "tradingagents.db"))
            src.backup(dst)
            src.close(); dst.close()
            log("Banco atual incluído (contém suas chaves de API: não compartilhe este instalador).")

    log("Compactando payload...")
    zip_dir(payload_dir, pkg_dir / "payload.zip", level=9)

    # PowerShell 5.1 precisa de BOM para ler acentos corretamente
    for name in ("install.ps1", "uninstall.ps1"):
        text = (INSTALLER_SRC / name).read_text(encoding="utf-8")
        (pkg_dir / name).write_text(text, encoding="utf-8-sig")
    shutil.copy2(INSTALLER_SRC / "setup.cmd", pkg_dir / "setup.cmd")

    target = work / f"TradingAgentsB3-Setup-{version}.exe"
    sed = work / "installer.sed"
    sed.write_text(SED.format(target=target, version=version, src=pkg_dir), encoding="mbcs")
    log("Gerando executável com IExpress (alguns minutos)...")
    run(["iexpress.exe", "/N", "/Q", str(sed)])
    if not target.exists():
        raise SystemExit("IExpress não gerou o executável.")
    final = DIST / target.name
    shutil.copy2(target, final)
    shutil.rmtree(work, ignore_errors=True)
    return final


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notes", default="", help="Notas da versão (aparecem no Cockpit)")
    ap.add_argument("--channel", default="", help="Canal de atualização já configurado no instalador")
    ap.add_argument("--publish", default="", help="Pasta do canal para copiar pacote + latest.json")
    ap.add_argument("--include-db", action="store_true", help="Inclui o banco atual no instalador")
    ap.add_argument("--skip-installer", action="store_true", help="Gera só o pacote de atualização")
    ap.add_argument("--skip-tests", action="store_true", help="Não roda a suíte de testes no runtime")
    a = ap.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    log(f"Versão {version}")
    DIST.mkdir(exist_ok=True)

    runtime = build_runtime()
    app_dir = BUILD / "work" / "app"
    stage_app(app_dir)
    if not a.skip_tests:
        run_tests_in_runtime(runtime)
    smoke_test_app(runtime, app_dir)

    # Pacote de atualização + manifesto
    app_zip = DIST / f"TradingAgentsB3-app-{version}.zip"
    zip_dir(app_dir, app_zip)
    manifest = {
        "version": version,
        "package": app_zip.name,
        "sha256": sha256(app_zip),
        "size": app_zip.stat().st_size,
        "notes": a.notes,
        "published_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (DIST / "latest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Pacote de atualização: {app_zip.name} ({app_zip.stat().st_size // 1024} KB)")

    if not a.skip_installer:
        exe = build_installer(runtime, app_dir, version, a.channel, a.include_db)
        log(f"Instalador: {exe.name} ({exe.stat().st_size // (1024 * 1024)} MB)")

    if a.publish:
        dest = Path(a.publish)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(app_zip, dest / app_zip.name)
        shutil.copy2(DIST / "latest.json", dest / "latest.json")  # por último: só aparece com o pacote pronto
        log(f"Publicado em {dest}")

    log(f"Pronto. Arquivos em {DIST}")


if __name__ == "__main__":
    main()
