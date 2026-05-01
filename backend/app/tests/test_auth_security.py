from app.auth.security import create_access_token, hash_password, verify_password
from app.models import UserRole


def test_password_hash_round_trip() -> None:
    hashed = hash_password("secret")
    assert hashed != "secret"
    assert verify_password("secret", hashed)
    assert not verify_password("wrong", hashed)


def test_create_access_token() -> None:
    token = create_access_token("user-id", UserRole.admin)
    assert token
    assert token.count(".") == 2
