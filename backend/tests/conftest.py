"""Shared pytest fixtures + credentials loaded from environment.

Test credentials live in `.env.test` (gitignored) or the shell environment —
NEVER inline in test source. This keeps secret scanners happy and lets CI/CD
inject role accounts without code edits.
"""
import os
from pathlib import Path
import pytest
from dotenv import load_dotenv

# Load .env.test if present (local dev convenience). Production CI sets env directly.
_ENV_TEST = Path(__file__).parent / ".env.test"
if _ENV_TEST.exists():
    load_dotenv(_ENV_TEST)


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"required env var {name} not set; populate .env.test or export it")
    return val


@pytest.fixture(scope="session")
def test_creds():
    """Role -> (email, password) loaded from environment, never literals."""
    return {
        "farmer": (_required("TEST_FARMER_EMAIL"), _required("TEST_FARMER_PASSWORD")),
        "buyer":  (_required("TEST_BUYER_EMAIL"),  _required("TEST_BUYER_PASSWORD")),
        "admin":  (_required("TEST_ADMIN_EMAIL"),  _required("TEST_ADMIN_PASSWORD")),
    }
