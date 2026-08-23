from scripts.seed_demo import DEMO_USER_EMAILS

from orderflow.modules.auth.schemas import LoginRequest


def test_demo_user_emails_pass_auth_validation() -> None:
    for email in DEMO_USER_EMAILS:
        payload = LoginRequest(email=email, password="demo-password")

        assert str(payload.email) == email
