"""
Validation layer.

Two kinds of checks live here:
  1. Cheap structural checks on raw user input (side is BUY/SELL, qty > 0, a
     LIMIT order actually has a price, ...). These run first and need no network.
  2. Exchange-filter checks against the symbol's live trading rules pulled from
     exchangeInfo (LOT_SIZE step, PRICE_FILTER tick, MIN_NOTIONAL). We round to
     the legal grid and reject anything that still can't trade, so the user gets
     a readable message instead of a cryptic -1013 / -4164 from Binance.

Decimal is used throughout so 0.1 + 0.2 style float dust never corrupts a
quantity or price.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation

from .exceptions import ValidationError

VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT", "STOP"}  # STOP = stop-limit on futures


# ----- structural input checks --------------------------------------------
def validate_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s.isalnum():
        raise ValidationError(f"Invalid symbol '{symbol}'. Expected e.g. BTCUSDT.")
    return s


def validate_side(side: str) -> str:
    s = (side or "").strip().upper()
    if s not in VALID_SIDES:
        raise ValidationError(f"Invalid side '{side}'. Use BUY or SELL.")
    return s


def validate_order_type(order_type: str) -> str:
    t = (order_type or "").strip().upper()
    if t not in VALID_ORDER_TYPES:
        raise ValidationError(
            f"Invalid order type '{order_type}'. Use MARKET, LIMIT or STOP."
        )
    return t


def _to_decimal(value, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValidationError(f"{field} must be a number, got '{value}'.") from exc
    return d


def validate_quantity(quantity) -> Decimal:
    q = _to_decimal(quantity, "quantity")
    if q <= 0:
        raise ValidationError("quantity must be greater than 0.")
    return q


def validate_price(price, *, required: bool) -> Decimal | None:
    if price is None:
        if required:
            raise ValidationError("price is required for LIMIT / STOP orders.")
        return None
    p = _to_decimal(price, "price")
    if p <= 0:
        raise ValidationError("price must be greater than 0.")
    return p


# ----- exchange-filter helpers --------------------------------------------
def round_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Round DOWN to the nearest multiple of step (never round qty/price up)."""
    if step == 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def extract_symbol_filters(exchange_info: dict, symbol: str) -> dict:
    """Pull the rules we care about for one symbol out of exchangeInfo."""
    for sym in exchange_info.get("symbols", []):
        if sym.get("symbol") == symbol:
            filters = {f["filterType"]: f for f in sym.get("filters", [])}
            return {
                "step_size": Decimal(filters["LOT_SIZE"]["stepSize"]),
                "min_qty": Decimal(filters["LOT_SIZE"]["minQty"]),
                "tick_size": Decimal(filters["PRICE_FILTER"]["tickSize"]),
                "min_notional": Decimal(
                    filters.get("MIN_NOTIONAL", {}).get("notional", "0")
                ),
                "quantity_precision": int(sym.get("quantityPrecision", 8)),
                "price_precision": int(sym.get("pricePrecision", 8)),
            }
    raise ValidationError(f"Symbol '{symbol}' not found on the exchange.")


def normalize_quantity(quantity: Decimal, filters: dict) -> Decimal:
    q = round_to_step(quantity, filters["step_size"])
    if q < filters["min_qty"]:
        raise ValidationError(
            f"quantity {quantity} is below the minimum {filters['min_qty']} "
            f"for this symbol."
        )
    return q


def normalize_price(price: Decimal, filters: dict) -> Decimal:
    return round_to_step(price, filters["tick_size"])


def check_min_notional(quantity: Decimal, price: Decimal, filters: dict) -> None:
    min_notional = filters["min_notional"]
    if min_notional > 0 and price * quantity < min_notional:
        raise ValidationError(
            f"Order notional {price * quantity} is below the exchange minimum "
            f"{min_notional}. Increase quantity or price."
        )
