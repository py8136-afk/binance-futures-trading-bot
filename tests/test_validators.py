"""
Offline tests for the validation layer: bad input is rejected, good input is
normalized, and quantities/prices are rounded DOWN to the exchange grid.
"""

from decimal import Decimal

import pytest

from bot import validators as v
from bot.exceptions import ValidationError

FILTERS = {
    "step_size": Decimal("0.001"),
    "min_qty": Decimal("0.001"),
    "tick_size": Decimal("0.10"),
    "min_notional": Decimal("5"),
    "quantity_precision": 3,
    "price_precision": 2,
}


# ----- structural -----
def test_side_accepts_lowercase():
    assert v.validate_side("buy") == "BUY"


def test_side_rejects_garbage():
    with pytest.raises(ValidationError):
        v.validate_side("long")


def test_symbol_uppercased():
    assert v.validate_symbol("btcusdt") == "BTCUSDT"


def test_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        v.validate_quantity(0)
    with pytest.raises(ValidationError):
        v.validate_quantity(-1)


def test_limit_price_required():
    with pytest.raises(ValidationError):
        v.validate_price(None, required=True)
    assert v.validate_price(None, required=False) is None


# ----- rounding -----
def test_round_quantity_down_to_step():
    q = v.normalize_quantity(Decimal("0.0034"), FILTERS)
    assert q == Decimal("0.003")


def test_round_price_to_tick():
    p = v.normalize_price(Decimal("50000.17"), FILTERS)
    assert p == Decimal("50000.10")


def test_below_min_qty_rejected():
    with pytest.raises(ValidationError):
        v.normalize_quantity(Decimal("0.0005"), FILTERS)


def test_min_notional_enforced():
    # 0.001 * 1000 = 1.0 < 5 -> reject
    with pytest.raises(ValidationError):
        v.check_min_notional(Decimal("0.001"), Decimal("1000"), FILTERS)
    # 0.001 * 6000 = 6.0 >= 5 -> ok
    v.check_min_notional(Decimal("0.001"), Decimal("6000"), FILTERS)


def test_extract_filters_from_exchange_info():
    info = {
        "symbols": [{
            "symbol": "BTCUSDT",
            "quantityPrecision": 3,
            "pricePrecision": 2,
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }]
    }
    f = v.extract_symbol_filters(info, "BTCUSDT")
    assert f["step_size"] == Decimal("0.001")
    assert f["tick_size"] == Decimal("0.10")
    assert f["min_notional"] == Decimal("5")
