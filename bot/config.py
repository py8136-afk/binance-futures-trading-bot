"""
Configuration loading and secret handling.

Everything sensitive (API key + secret) lives in a local `.env` file that is
git-ignored and never logged in the clear. `redact()` is used everywhere we
might otherwise leak a key into a log line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from .exceptions import ConfigError

# Binance USDT-M Futures *testnet*. Hard-coded as the default so a fresh clone
# points at fake-money by mistake, never real funds.
DEFAULT_BASE_URL = "https://testnet.binancefuture.com"


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_secret: str
    base_url: str = DEFAULT_BASE_URL
    recv_window: int = 5000      # ms the server will tolerate our timestamp by
    timeout: float = 10.0        # seconds per HTTP request

    def redacted_key(self) -> str:
        return redact(self.api_key)


def redact(secret: str | None) -> str:
    """Mask a secret, keeping just enough to eyeball-match it in logs."""
    if not secret:
        return "<missing>"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def load_settings(require_keys: bool = True) -> Settings:
    """
    Load settings from environment / .env.

    require_keys=False is used by --dry-run and the offline tests, where we want
    to construct and *sign* a request without needing real credentials present.
    """
    load_dotenv()  # no-op if .env is absent; real env vars still win

    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    base_url = os.getenv("BINANCE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

    if require_keys and (not api_key or not api_secret):
        raise ConfigError(
            "BINANCE_API_KEY / BINANCE_API_SECRET not set. "
            "Copy .env.example to .env and paste your testnet keys."
        )

    try:
        recv_window = int(os.getenv("BINANCE_RECV_WINDOW", "5000"))
        timeout = float(os.getenv("BINANCE_TIMEOUT", "10"))
    except ValueError as exc:
        raise ConfigError(f"Invalid numeric setting in environment: {exc}") from exc

    return Settings(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url,
        recv_window=recv_window,
        timeout=timeout,
    )
