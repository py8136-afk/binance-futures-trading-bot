"""
Custom exception hierarchy for the trading bot.

Why a hierarchy instead of bare `Exception`:
the CLI layer can catch `BotError` once and present a clean message to the
user, while internally we still distinguish *why* something failed (bad input
vs. the exchange rejecting us vs. the network dying). That separation is what
lets logging stay precise and the user-facing output stay calm.
"""


class BotError(Exception):
    """Base class for every error this application raises on purpose."""


class ConfigError(BotError):
    """Missing/invalid configuration (e.g. API keys not set in .env)."""


class ValidationError(BotError):
    """User input failed a local check before we ever hit the network."""


class BinanceAPIError(BotError):
    """
    Binance accepted the request but rejected it logically, or returned a
    non-2xx HTTP status. Carries the exchange's own error code + message so
    callers can react to specific cases (e.g. -1021 timestamp drift).
    """

    def __init__(self, code, message, http_status=None):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(f"Binance API error {code}: {message}")


class NetworkError(BotError):
    """The request never got a clean answer (timeout, DNS, connection reset)."""
