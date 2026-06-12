"""
Proves the HMAC-SHA256 signing is correct WITHOUT any network access.

Strategy: cross-implementation equivalence. The client's signing must match a
second, independent HMAC computation done with Python's stdlib over the same
input. If a future change breaks the encoding, key order, or digest algorithm,
this fails immediately. This is the most important correctness guarantee here.
"""

import hashlib
import hmac

from bot.client import BinanceFuturesClient
from bot.config import Settings

SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0"
QUERY = (
    "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1"
    "&price=0.1&recvWindow=5000&timestamp=1499827319559"
)


def _reference_sig(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _client(secret: str) -> BinanceFuturesClient:
    return BinanceFuturesClient(Settings(api_key="dummy", api_secret=secret))


def test_signing_matches_independent_reference():
    client = _client(SECRET)
    assert client._sign(QUERY) == _reference_sig(SECRET, QUERY)


def test_signature_is_deterministic():
    client = _client(SECRET)
    assert client._sign(QUERY) == client._sign(QUERY)


def test_signature_changes_with_secret():
    assert _client("secret-a")._sign(QUERY) != _client("secret-b")._sign(QUERY)


def test_signature_changes_with_payload():
    client = _client(SECRET)
    assert client._sign(QUERY) != client._sign(QUERY + "&extra=1")


def test_signed_query_appends_signature_and_required_fields():
    client = _client(SECRET)
    signed = client.build_signed_query({"symbol": "BTCUSDT", "side": "BUY"})
    assert "signature=" in signed
    assert "timestamp=" in signed
    assert "recvWindow=" in signed
    body, sig = signed.rsplit("&signature=", 1)
    assert _reference_sig(SECRET, body) == sig
