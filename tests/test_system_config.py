import socket

import pytest
from fastapi import HTTPException

from src import system_config
from src.models import User
from src.schemas import NetworkConfigUpdate


def test_set_env_values_preserva_resto(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comentario\nSECRET_KEY=abc=def==\nHOST=0.0.0.0\nPORT=8000\nADMIN_PASSWORD=x\n", encoding="utf-8")
    system_config.set_env_values(env, {"HOST": "127.0.0.1", "PORT": "8001", "NOVA": "1"})
    texto = env.read_text(encoding="utf-8")
    assert "# comentario" in texto and "SECRET_KEY=abc=def==" in texto and "ADMIN_PASSWORD=x" in texto
    valores = system_config.read_env(env)
    assert valores["HOST"] == "127.0.0.1" and valores["PORT"] == "8001" and valores["NOVA"] == "1"
    assert texto.count("PORT=") == 1


def test_read_env_aceita_bom(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PORT=8090\n", encoding="utf-8-sig")
    assert system_config.read_env(env)["PORT"] == "8090"


def test_port_is_free():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        ocupada = s.getsockname()[1]
        assert system_config.port_is_free(ocupada) is False


def test_endpoint_valida_e_grava(tmp_path, monkeypatch, ):
    from src.web import api_routes
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    user = User(username="t", hashed_password="x")

    env = tmp_path / ".env"
    env.write_text("PORT=8000\nHOST=0.0.0.0\n", encoding="utf-8")
    monkeypatch.setattr(system_config, "env_path", lambda: env)
    monkeypatch.setattr(system_config, "INSTALL_ROOT", None)
    monkeypatch.setattr(system_config, "PORT", 8000)
    monkeypatch.setattr(system_config, "HOST", "0.0.0.0")

    with pytest.raises(HTTPException):  # endereço inválido
        api_routes.set_network_config(NetworkConfigUpdate(port=8001, host="10.0.0.1"), db, user)
    with pytest.raises(HTTPException):  # nada mudou
        api_routes.set_network_config(NetworkConfigUpdate(port=8000, host="0.0.0.0"), db, user)

    res = api_routes.set_network_config(NetworkConfigUpdate(port=8001, host="127.0.0.1"), db, user)
    assert res["reiniciando"] is False and res["nova_url"] == "http://127.0.0.1:8001"
    assert system_config.read_env(env) == {"PORT": "8001", "HOST": "127.0.0.1"}

    with pytest.raises(Exception):  # porta fora da faixa
        NetworkConfigUpdate(port=80, host="127.0.0.1")
