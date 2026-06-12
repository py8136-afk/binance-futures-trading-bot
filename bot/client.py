"""
Low-level Binance USDT-M Futures REST client.

This is the wire layer. It does exactly four hard things and nothing else:
  1. Keeps our clock in sync with Binance (avoids -1021 timestamp errors).
  2. Signs SIGNED endpoints with HMAC-SHA256 over the exact query string.
  3. Maps Binance's {"code","msg"} errors and network failures onto our
     exception hierarchy.
  4. Logs every request and response (redacted) for the audit trail.

Deliberate safety rule: we retry idempotent GETs on transient network errors,
but we NEVER retry a POST /order. Retrying an order that may have already been
accepted would open a duplicate position. One order in == at most one order out.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import requests

from .config import Settings
from .exceptions import BinanceAPIError, NetworkError

# Endpoint paths (USDT-M futures).
PATH_TIME = "/fapi/v1/time"
PATH_EXCHANGE_INFO = "/fapi/v1/exchangeInfo"
PATH_TICKER_PRICE = "/fapi/v1/ticker/price"
PATH_ORDER = "/fapi/v1/order"
PATH_BALANCE = "/fapi/v2/balance"

_TIMESTAMP_DRIFT_CODE = -1021  # "Timestamp for this request is outside recvWindow"


class BinanceFuturesClient:
    def __init__(self, settings: Settings, logger: logging.Logger | None = None):
        self.settings = settings
        self.log = logger or logging.getLogger("bot")
        self._time_offset_ms = 0  # serverTime - localTime, learned via sync_time()
        self._session = requests.Session()
        self._session.headers.update({"X-MBX-APIKEY": settings.api_key})

    # ----- clock -----------------------------------------------------------
    def sync_time(self) -> int:
        """Learn the offset between our clock and Binance's. Call once at start."""
        server_time = self.get_server_time()
        local_ms = int(time.time() * 1000)
        self._time_offset_ms = server_time - local_ms
        self.log.debug("Clock synced. offset=%d ms", self._time_offset_ms)
        return self._time_offset_ms

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + self._time_offset_ms

    # ----- signing ---------------------------------------------------------
    def _sign(self, query_string: str) -> str:
        return hmac.new(
            self.settings.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def build_signed_query(self, params: dict) -> str:
        """
        Build the exact signed query string for a SIGNED request.
        Exposed (not private) so --dry-run and tests can inspect/verify it.
        """
        payload = dict(params)
        payload.setdefault("timestamp", self._timestamp())
        payload.setdefault("recvWindow", self.settings.recv_window)
        query_string = urlencode(payload)
        signature = self._sign(query_string)
        return f"{query_string}&signature={signature}"

    # ----- transport -------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        signed: bool = False,
        retry: bool = False,
        _resynced: bool = False,
    ) -> dict | list:
        params = params or {}
        url = f"{self.settings.base_url}{path}"

        if signed:
            query = self.build_signed_query(params)
        else:
            query = urlencode(params)

        full_url = f"{url}?{query}" if query else url
        self.log.debug("REQUEST %s %s%s", method, path, f"?{query}" if query else "")

        attempts = 3 if retry else 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                resp = self._session.request(
                    method, full_url, timeout=self.settings.timeout
                )
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                self.log.warning(
                    "Network error (attempt %d/%d) on %s: %s",
                    attempt, attempts, path, exc,
                )
                if attempt < attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise NetworkError(f"Request to {path} failed: {exc}") from exc

            return self._handle_response(
                resp, method, path, params, signed, retry, _resynced
            )

        # Unreachable, but keeps type-checkers happy.
        raise NetworkError(str(last_exc))

    def _handle_response(
        self, resp, method, path, params, signed, retry, _resynced
    ):
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}

        self.log.debug("RESPONSE %s %s -> %s | %s", method, path, resp.status_code, body)

        if resp.status_code == 200:
            return body

        # Binance puts logical errors in the body even on non-200.
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("msg") if isinstance(body, dict) else resp.text

        # Self-heal clock drift exactly once.
        if code == _TIMESTAMP_DRIFT_CODE and not _resynced:
            self.log.info("Timestamp drift detected; re-syncing clock and retrying.")
            self.sync_time()
            return self._request(
                method, path, params, signed=signed, retry=retry, _resynced=True
            )

        raise BinanceAPIError(code, msg, http_status=resp.status_code)

    # ----- public endpoints -----------------------------------------------
    def get_server_time(self) -> int:
        data = self._request("GET", PATH_TIME, retry=True)
        return int(data["serverTime"])

    def get_exchange_info(self) -> dict:
        return self._request("GET", PATH_EXCHANGE_INFO, retry=True)

    def get_ticker_price(self, symbol: str) -> dict:
        return self._request(
            "GET", PATH_TICKER_PRICE, params={"symbol": symbol}, retry=True
        )

    def get_balance(self) -> list:
        return self._request("GET", PATH_BALANCE, signed=True, retry=True)

    def new_order(self, params: dict) -> dict:
        # NOTE: retry=False on purpose. Never resend an order.
        return self._request("POST", PATH_ORDER, params=params, signed=True, retry=False)

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self._request(
            "GET",
            PATH_ORDER,
            params={"symbol": symbol, "orderId": order_id},
            signed=True,
            retry=True,
        )
