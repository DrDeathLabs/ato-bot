from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

import jwt

from app.core.security import (
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_token,
    settings,
)


class TokenSecurityTests(unittest.TestCase):
    def test_access_token_contains_required_identity_and_security_claims(self) -> None:
        token = create_access_token("42", "assessor")
        payload = decode_token(token)

        self.assertEqual(payload["sub"], "42")
        self.assertEqual(payload["role"], "assessor")
        self.assertEqual(payload["type"], "access")
        self.assertEqual(payload["iss"], settings.jwt_issuer)
        self.assertEqual(payload["aud"], settings.jwt_audience)
        self.assertTrue(payload["jti"])

    def test_access_tokens_are_unique_for_the_same_subject(self) -> None:
        first = create_access_token("42", "assessor")
        second = create_access_token("42", "assessor")

        self.assertNotEqual(first, second)
        self.assertNotEqual(decode_token(first)["jti"], decode_token(second)["jti"])

    def test_refresh_token_contains_no_role_claim(self) -> None:
        payload = decode_token(create_refresh_token("42"))

        self.assertEqual(payload["type"], "refresh")
        self.assertNotIn("role", payload)

    def test_expired_token_is_rejected(self) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "42",
                "type": "access",
                "role": "assessor",
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "iat": now - timedelta(minutes=2),
                "exp": now - timedelta(minutes=1),
                "jti": "expired-token",
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        with self.assertRaises(TokenValidationError):
            decode_token(token)

    def test_wrong_audience_is_rejected(self) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "42",
                "type": "access",
                "role": "assessor",
                "iss": settings.jwt_issuer,
                "aud": "different-service",
                "iat": now,
                "exp": now + timedelta(minutes=5),
                "jti": "wrong-audience",
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        with self.assertRaises(TokenValidationError):
            decode_token(token)

    def test_missing_required_claim_is_rejected(self) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "42",
                "type": "access",
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )

        with self.assertRaises(TokenValidationError):
            decode_token(token)


if __name__ == "__main__":
    unittest.main()
