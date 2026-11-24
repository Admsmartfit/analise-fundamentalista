import hashlib
import json
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import Base
from src.models import SystemSetting
from src.updater import manager


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _make_pkg(path, version="99.0.0", completo=True):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("VERSION", version)
        z.writestr("main.py", "print('x')")
        if completo:
            z.writestr("launcher.py", "")
            z.writestr("src/__init__.py", "")
    return path


def _publish(folder, version="99.0.0", sha=None):
    pkg = _make_pkg(folder / f"TradingAgentsB3-app-{version}.zip", version)
    digest = sha or hashlib.sha256(pkg.read_bytes()).hexdigest()
    (folder / "latest.json").write_text(json.dumps({
        "version": version, "package": pkg.name, "sha256": digest, "notes": "Novidades"}), encoding="utf-8")
    return pkg


def test_parse_version():
    assert manager.parse_version("8.1.0") > manager.parse_version("8.0.9")
    assert manager.parse_version("v8.10") > manager.parse_version("8.9.5")
    assert manager.parse_version("8.1") == manager.parse_version("8.1.0")


def test_check_por_pasta_e_canal_do_cockpit(db, tmp_path):
    _publish(tmp_path)
    db.add(SystemSetting(key="update_channel", value=str(tmp_path)))
    db.commit()
    info = manager.check(db)
    assert info["versao_disponivel"] == "99.0.0"
    assert info["tem_atualizacao"] is True
    assert info["notas"] == "Novidades"


def test_check_sem_canal(db, monkeypatch):
    monkeypatch.setattr(manager, "UPDATE_CHANNEL", "")
    with pytest.raises(manager.UpdateError, match="não configurado"):
        manager.check(db)


def test_download_confere_sha256(db, tmp_path, monkeypatch):
    canal = tmp_path / "canal"
    canal.mkdir()
    monkeypatch.setattr(manager, "UPDATES_DIR", tmp_path / "updates")
    db.add(SystemSetting(key="update_channel", value=str(canal)))
    db.commit()

    _publish(canal)
    baixado = manager.download_package(db)
    assert manager.validate_package(baixado) == "99.0.0"

    _publish(canal, sha="0" * 64)
    with pytest.raises(manager.UpdateError, match="SHA-256"):
        manager.download_package(db)


def test_validate_package_rejeita_zip_incompleto(tmp_path):
    with pytest.raises(manager.UpdateError, match="launcher.py"):
        manager.validate_package(_make_pkg(tmp_path / "x.zip", completo=False))
    (tmp_path / "nao.zip").write_text("isto não é zip")
    with pytest.raises(manager.UpdateError, match="zip válido"):
        manager.validate_package(tmp_path / "nao.zip")


def test_apply_recusa_em_modo_desenvolvimento(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "INSTALL_ROOT", None)
    with pytest.raises(manager.UpdateError, match="versão instalada"):
        manager.launch_apply(_make_pkg(tmp_path / "p.zip"))


def test_backup_database(tmp_path, monkeypatch):
    import sqlite3
    db_file = tmp_path / "t.db"
    c = sqlite3.connect(db_file)
    c.execute("create table x(a)")
    c.execute("insert into x values (1)")
    c.commit()
    c.close()
    monkeypatch.setattr(manager, "DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setattr(manager, "BACKUPS_DIR", tmp_path / "bk")
    out = manager.backup_database("teste")
    assert sqlite3.connect(out).execute("select a from x").fetchone() == (1,)


def test_canal_github_fixa_no_commit_mais_recente(monkeypatch):
    sha = "a" * 40

    class _R:
        status_code = 200
        text = sha
    chamadas = []
    monkeypatch.setattr(manager.httpx, "get", lambda url, **kw: (chamadas.append(url), _R())[1])
    raw = "https://raw.githubusercontent.com/Dono/repo/main/updates/latest.json"
    assert manager._pin_github_raw_to_latest_commit(raw) == \
        f"https://raw.githubusercontent.com/Dono/repo/{sha}/updates/latest.json"
    assert chamadas == ["https://api.github.com/repos/Dono/repo/commits/main"]
    # URL que não é do GitHub, ou já fixada num commit: não mexe
    assert manager._pin_github_raw_to_latest_commit("https://exemplo.com/latest.json") == "https://exemplo.com/latest.json"
    fixada = f"https://raw.githubusercontent.com/Dono/repo/{sha}/latest.json"
    assert manager._pin_github_raw_to_latest_commit(fixada) == fixada


def test_canal_github_sem_api_usa_url_original(monkeypatch):
    def falha(*a, **k):
        raise RuntimeError("sem internet")
    monkeypatch.setattr(manager.httpx, "get", falha)
    raw = "https://raw.githubusercontent.com/Dono/repo/main/updates/latest.json"
    assert manager._pin_github_raw_to_latest_commit(raw) == raw
