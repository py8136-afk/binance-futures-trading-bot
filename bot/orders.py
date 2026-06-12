"""
Order service — the layer the CLI actually talks to.

Responsibilities:
  - turn validated user intent into a correct Binance order payload,
  - apply the symbol's exchange filters (rounding qty/price, notional check),
  - attach a unique client order id so a given click is idempotent,
  - hand the payload to the client and return a tidy result dict.

It caches exchangeInfo for the lifetime of the process so a multi-order session
doesn't re-download the (large) exchange-info blob every time.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from . import validators as v
from .client import BinanceFuturesClient


class OrderService:
    def __init__(self, client: BinanceFuturesClient, logger: logging.Logger | None = None):
        self.client = client
        self.log = logger or logging.getLogger("bot")
        self._exchange_info: dict | None = None
        self._filter_cache: dict[str, dict] = {}

    # ----- exchange info ---------------------------------------------------
    def _filters_for(self, symbol: str) -> dict:
        if symbol not in self._filter_cache:
            if self._exchange_info is None:
                self._exchange_info = self.client.get_exchange_info()
            self._filter_cache[symbol] = v.extract_symbol_filters(
                self._exchange_info, symbol
            )
        return self._filter_cache[symbol]

    @staticmethod
    def _client_order_id() -> str:
        # Short, unique, human-greppable in logs.
        return f"bot-{uuid.uuid4().hex[:16]}"

    # ----- public placement API -------------------------------------------
    def place_market(self, symbol: str, side: str, quantity) -> dict:
        symbol = v.validate_symbol(symbol)
        side = v.validate_side(side)
        qty = v.validate_quantity(quantity)

        filters = self._filters_for(symbol)
        qty = v.normalize_quantity(qty, filters)

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": _fmt(qty),
            "newClientOrderId": self._client_order_id(),
        }
        return self._submit(params)

    def place_limit(self, symbol: str, side: str, quantity, price) -> dict:
        symbol = v.validate_symbol(symbol)
        side = v.validate_side(side)
        qty = v.validate_quantity(quantity)
        px = v.validate_price(price, required=True)

        filters = self._filters_for(symbol)
        qty = v.normalize_quantity(qty, filters)
        px = v.normalize_price(px, filters)
        v.check_min_notional(qty, px, filters)

        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": _fmt(qty),
            "price": _fmt(px),
            "newClientOrderId": self._client_order_id(),
        }
        return self._submit(params)

    def place_stop_market(self, symbol: str, side: str, quantity, stop_price) -> dict:
        """Bonus order type. Binance 'STOP' = stop-limit: needs price + stopPrice."""
        symbol = v.validate_symbol(symbol)
        side = v.validate_side(side)
        qty = v.validate_quantity(quantity)
        stop = v.validate_price(stop_price, required=True)

        filters = self._filters_for(symbol)
        qty = v.normalize_quantity(qty, filters)
        stop = v.normalize_price(stop, filters)

        params = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "quantity": _fmt(qty),
            "stopPrice": _fmt(stop),
            "newClientOrderId": self._client_order_id(),
        }
        return self._submit(params)

    # ----- internal --------------------------------------------------------
    def _submit(self, params: dict) -> dict:
        self.log.info(
            "Placing %s %s %s qty=%s%s",
            params["type"],
            params["side"],
            params["symbol"],
            params["quantity"],
            f" price={params['price']}" if "price" in params else "",
        )
        raw = self.client.new_order(params)
        result = _summarize(raw)
        self.log.info(
            "Order ACK id=%s status=%s executedQty=%s avgPrice=%s",
            result["orderId"], result["status"],
            result["executedQty"], result["avgPrice"],
        )
        return result

    def build_only(self, order_type: str, symbol: str, side: str,
                    quantity, price=None, stop_price=None) -> dict:
        """
        Construct + validate the payload WITHOUT sending. Powers --dry-run.
        Returns the exact params dict that would be POSTed.
        """
        ot = v.validate_order_type(order_type)
        if ot == "MARKET":
            symbol = v.validate_symbol(symbol)
            side = v.validate_side(side)
            qty = v.validate_quantity(quantity)
            return {
                "symbol": symbol, "side": side, "type": "MARKET",
                "quantity": str(qty), "newClientOrderId": self._client_order_id(),
            }
        if ot == "LIMIT":
            symbol = v.validate_symbol(symbol)
            side = v.validate_side(side)
            qty = v.validate_quantity(quantity)
            px = v.validate_price(price, required=True)
            return {
                "symbol": symbol, "side": side, "type": "LIMIT", "timeInForce": "GTC",
                "quantity": str(qty), "price": str(px),
                "newClientOrderId": self._client_order_id(),
            }
        # STOP
        symbol = v.validate_symbol(symbol)
        side = v.validate_side(side)
        qty = v.validate_quantity(quantity)
        stop = v.validate_price(stop_price, required=True)
        return {
            "symbol": symbol, "side": side, "type": "STOP_MARKET", "timeInForce": "GTC",
            "quantity": str(qty), "price": str(px), "stopPrice": str(stop),
            "newClientOrderId": self._client_order_id(),
        }


def _fmt(d: Decimal) -> str:
    """Decimal -> plain string Binance accepts (no scientific notation)."""
    return format(d.normalize(), "f")


def _summarize(raw: dict) -> dict:
    """Pull the fields the task asks us to print out of Binance's response."""
    return {
        "orderId": raw.get("orderId"),
        "clientOrderId": raw.get("clientOrderId"),
        "symbol": raw.get("symbol"),
        "side": raw.get("side"),
        "type": raw.get("type"),
        "status": raw.get("status"),
        "executedQty": raw.get("executedQty", "0"),
        "avgPrice": raw.get("avgPrice", "0"),
        "price": raw.get("price", "0"),
        "raw": raw,
    }
