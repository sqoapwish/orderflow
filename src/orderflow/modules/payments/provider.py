import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class MockPaymentSession:
    provider_payment_id: str
    checkout_url: str
    expires_at: datetime


class MockPaymentProvider:
    name = "mock"

    def __init__(self, *, webhook_secret: str, session_ttl_minutes: int) -> None:
        self._secret = webhook_secret.encode()
        self._session_ttl_minutes = session_ttl_minutes

    def create_session(self) -> MockPaymentSession:
        provider_payment_id = f"mock_pay_{uuid4().hex}"
        return MockPaymentSession(
            provider_payment_id=provider_payment_id,
            checkout_url=f"https://mock-payments.local/pay/{provider_payment_id}",
            expires_at=datetime.now(UTC) + timedelta(minutes=self._session_ttl_minutes),
        )

    def create_refund_id(self) -> str:
        return f"mock_ref_{uuid4().hex}"

    def sign_webhook(self, *, timestamp: int, body: bytes) -> str:
        message = str(timestamp).encode() + b"." + body
        digest = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def verify_webhook(self, *, timestamp: int, body: bytes, signature: str) -> bool:
        expected = self.sign_webhook(timestamp=timestamp, body=body)
        return hmac.compare_digest(expected, signature)
