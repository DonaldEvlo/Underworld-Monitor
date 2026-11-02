import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    TokenType,
    _create_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_the_plaintext(self):
        assert (
            hash_password("correct-horse-battery-staple")
            != "correct-horse-battery-staple"
        )

    def test_verify_accepts_the_right_password(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed)

    def test_verify_rejects_a_wrong_password(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert not verify_password("wrong-password", hashed)

    def test_same_password_produces_different_hashes(self):
        # argon2 sale chaque hash -- deux hash du meme mot de passe ne doivent
        # jamais etre identiques (sinon ils fuiteraient l'egalite des mots de passe).
        assert hash_password("same-password") != hash_password("same-password")


class TestTokens:
    def test_access_token_round_trips_to_the_original_user_id(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        assert decode_token(token, TokenType.ACCESS) == user_id

    def test_refresh_token_round_trips_to_the_original_user_id(self):
        user_id = uuid.uuid4()
        token = create_refresh_token(user_id)
        assert decode_token(token, TokenType.REFRESH) == user_id

    def test_refresh_token_rejected_when_access_token_expected(self):
        token = create_refresh_token(uuid.uuid4())
        with pytest.raises(InvalidTokenError):
            decode_token(token, TokenType.ACCESS)

    def test_access_token_rejected_when_refresh_token_expected(self):
        token = create_access_token(uuid.uuid4())
        with pytest.raises(InvalidTokenError):
            decode_token(token, TokenType.REFRESH)

    def test_expired_token_is_rejected(self):
        token = _create_token(uuid.uuid4(), TokenType.ACCESS, timedelta(seconds=-1))
        with pytest.raises(InvalidTokenError):
            decode_token(token, TokenType.ACCESS)

    def test_tampered_signature_is_rejected(self):
        token = create_access_token(uuid.uuid4())
        with pytest.raises(InvalidTokenError):
            decode_token(token + "tampered", TokenType.ACCESS)

    def test_token_signed_with_a_different_secret_is_rejected(self):
        payload = jwt.decode(
            create_access_token(uuid.uuid4()), options={"verify_signature": False}
        )
        forged = jwt.encode(payload, "attacker-controlled-secret", algorithm="HS256")
        with pytest.raises(InvalidTokenError):
            decode_token(forged, TokenType.ACCESS)


class TestSecretsAuDemarrage:
    """L'API refuse de démarrer avec une clé de signature d'exemple."""

    @pytest.mark.parametrize("faible", ["", "changeme"])
    def test_cle_par_defaut_refusee(self, faible):
        from app.core.config import Settings, verifier_secrets

        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            verifier_secrets(Settings(JWT_SECRET_KEY=faible))

    def test_cle_aleatoire_acceptee(self):
        from app.core.config import Settings, verifier_secrets

        verifier_secrets(Settings(JWT_SECRET_KEY="a3f9" * 16))
