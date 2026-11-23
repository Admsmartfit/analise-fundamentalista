import pytest
from src.auth.security import verify_password, get_password_hash, create_access_token
from jose import jwt
from src.config import SECRET_KEY, ALGORITHM

def test_password_hashing():
    password = "secret_password_123"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False

def test_jwt_token_creation_and_validation():
    data = {"sub": "test_trader"}
    token = create_access_token(data)
    assert isinstance(token, str)
    decoded = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["sub"] == "test_trader"
    assert "exp" in decoded
