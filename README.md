# Binance Futures Testnet Trading Bot

A small, production-shaped Python application that places **Market**, **Limit**,
and **Stop-Limit** orders on the **Binance USDT-M Futures Testnet**. It is built
around a hand-signed REST client (no SDK), validates every order against the
exchange's live trading filters *before* sending, and logs every request,
response, and error to a rotating log file with secrets redacted.

> Testnet only. The base URL defaults to `https://testnet.binancefuture.com`,
> so a fresh clone trades fake money. No real funds are ever at risk.

---

## Highlights

- **No SDK — direct signed REST.** HMAC-SHA256 request signing implemented by
  hand, verified by an offline test against an independent reference. Fewer
  dependencies, nothing to break on a library bump, and a clear demonstration of
  how the Binance signed-endpoint protocol actually works.
- **Validate before you send.** Pulls `exchangeInfo`, then rounds quantity to
  `LOT_SIZE.stepSize`, rounds price to `PRICE_FILTER.tickSize`, and checks
  `MIN_NOTIONAL` locally — so you get a readable error instead of a cryptic
  `-1013 / -4164` filter rejection from the exchange.
- **Safe by construction.** Clock auto-syncs with Binance to avoid `-1021`
  timestamp errors; each order carries a unique `newClientOrderId` for
  idempotency; transient network errors retry **only** on idempotent GETs — an
  order POST is **never** retried, so you can never accidentally double-fill.
- **Logging that's useful, not noisy.** Full request/response JSON at DEBUG in a
  rotating file (`logs/bot.log`); clean one-liners at INFO on the console; API
  keys and signatures scrubbed from every log line.
- **Clean separation.** Transport (`client.py`), order logic (`orders.py`),
  validation (`validators.py`), and CLI (`cli.py`) are independent and testable.

**Bonuses implemented:** a third order type (**Stop-Limit**) *and* an enhanced
CLI UX (typed arguments, rich tables/panels, a `--dry-run` mode, plus `balance`,
`price`, and `exchange-info` helper commands).

---

## Project structure

```
binance-futures-bot/
├── bot/
│   ├── __init__.py
│   ├── config.py          # .env loading, settings, secret redaction
│   ├── exceptions.py      # BotError -> Config / Validation / BinanceAPI / Network
│   ├── logging_config.py  # rotating file + console handlers, redaction filter
│   ├── client.py          # signed transport: time-sync, sign, request, error-map
│   ├── orders.py          # market / limit / stop-limit + exchangeInfo cache
│   └── validators.py      # input + filter validation, step/tick rounding
├── cli.py                 # Typer CLI entry point
├── tests/
│   ├── test_signing.py    # HMAC signing correctness (offline)
│   └── test_validators.py # input validation + rounding (offline)
├── logs/                  # bot.log is written here at runtime
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Setup

**Requirements:** Python 3.9+

1. **Get testnet API keys.** Register and log in at
   <https://testnet.binancefuture.com>, open the **API Key** tab, and generate a
   key + secret.

2. **Clone / unzip, then create a virtual environment:**
   ```bash
   cd binance-futures-bot
   python -m venv venv
   source venv/bin/activate          # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Add your keys:**
   ```bash
   cp .env.example .env
   # open .env and paste your testnet key + secret
   ```

---

## Usage

Check connectivity and credentials first:

```bash
python cli.py balance
python cli.py price BTCUSDT
python cli.py exchange-info BTCUSDT
```

Place orders:

```bash
# Market
python cli.py order BTCUSDT BUY MARKET --qty 0.01

# Limit (price required)
python cli.py order BTCUSDT BUY LIMIT --qty 0.01 --price 50000

# Stop-Limit (bonus): price + stop-price required
python cli.py order BTCUSDT SELL STOP --qty 0.01 --price 49000 --stop-price 49500
```

Inspect what *would* be sent, fully signed, without sending it:

```bash
python cli.py order BTCUSDT BUY LIMIT --qty 0.01 --price 50000 --dry-run
```

Every command prints an **order request summary**, the **order response**
(`orderId`, `status`, `executedQty`, `avgPrice`), and a clear success/failure
message. Full `--help` is available on every command (`python cli.py order --help`).

---

## Logging

- `logs/bot.log` — DEBUG, full request/response/error detail, rotated at ~1 MB
  (3 backups). This is the audit trail.
- Console — INFO, human-readable summaries.
- API keys and signatures are redacted in **both** sinks.

Running one Market order and one Limit order against the testnet produces the
sample logs to submit; they are written to `logs/bot.log`.

---

## Running the tests

```bash
python -m pytest -q
```

The suite is fully offline (no network, no keys): it verifies HMAC signing
against an independent reference implementation and checks input validation plus
step/tick rounding.

---

## Assumptions

- **Testnet, USDT-M, one-way position mode** (no `positionSide` / hedge-mode
  handling). The default account on the futures testnet is one-way.
- **Stop-Limit uses Binance type `STOP`** (a stop with a limit price), which
  requires both `price` and `stopPrice`. `STOP_MARKET` is not used.
- **Time-in-force `GTC`** for Limit and Stop-Limit orders.
- Quantity and price are **rounded down** to the exchange grid; if the rounded
  quantity falls below `minQty`, the order is rejected with a clear message
  rather than silently altered.
- The network layer retries transient failures on **idempotent GET** requests
  only. Order placement (POST) is never retried.
- One process == short-lived session, so `exchangeInfo` is cached in memory for
  that run.

---

## Error handling

All anticipated failures raise a typed exception (`ConfigError`,
`ValidationError`, `BinanceAPIError`, `NetworkError`) that the CLI catches and
renders as a single clean failure panel, while the full detail (including the
exchange's own error code and message) is written to the log file.
