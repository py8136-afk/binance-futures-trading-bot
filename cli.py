"""
CLI entry point.

Thin on purpose: it parses/normalizes arguments, wires up the client + order
service, calls the right method, and renders the result. All the real logic
lives in the bot/ package so it stays testable and reusable.

Examples
--------
  python cli.py balance
  python cli.py price BTCUSDT
  python cli.py order BTCUSDT BUY MARKET --qty 0.01
  python cli.py order BTCUSDT BUY LIMIT  --qty 0.01 --price 50000
  python cli.py order BTCUSDT SELL STOP  --qty 0.01 --price 49000 --stop-price 49500
  python cli.py order BTCUSDT BUY LIMIT  --qty 0.01 --price 50000 --dry-run
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from bot.client import BinanceFuturesClient
from bot.config import load_settings
from bot.exceptions import BotError
from bot.logging_config import setup_logging
from bot.orders import OrderService

app = typer.Typer(add_completion=False, help="Binance Futures Testnet trading bot.")
console = Console()


def _service(require_keys: bool = True) -> tuple[BinanceFuturesClient, OrderService, logging.Logger]:
    logger = setup_logging()
    settings = load_settings(require_keys=require_keys)
    client = BinanceFuturesClient(settings, logger)
    if require_keys:
        client.sync_time()  # align clock before any signed call
    return client, OrderService(client, logger), logger


def _fail(message: str) -> None:
    console.print(Panel(f"[bold red]✗ {message}[/]", title="Failed", border_style="red"))
    raise typer.Exit(code=1)


@app.command()
def order(
    symbol: str = typer.Argument(..., help="e.g. BTCUSDT"),
    side: str = typer.Argument(..., help="BUY or SELL"),
    order_type: str = typer.Argument(..., metavar="TYPE", help="MARKET, LIMIT or STOP"),
    qty: float = typer.Option(..., "--qty", "-q", help="Order quantity"),
    price: Optional[float] = typer.Option(None, "--price", "-p", help="Required for LIMIT/STOP"),
    stop_price: Optional[float] = typer.Option(None, "--stop-price", "-s", help="Required for STOP"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build + sign but do NOT send"),
):
    """Place a MARKET, LIMIT or STOP (stop-limit) order."""
    ot = order_type.upper()

    # Request summary up front, before we touch the network.
    summary = Table(title="Order Request", show_header=False, border_style="cyan")
    summary.add_row("Symbol", symbol.upper())
    summary.add_row("Side", side.upper())
    summary.add_row("Type", ot)
    summary.add_row("Quantity", str(qty))
    if price is not None:
        summary.add_row("Price", str(price))
    if stop_price is not None:
        summary.add_row("Stop Price", str(stop_price))
    console.print(summary)

    try:
        if dry_run:
            # No keys needed; show the exact signed payload that WOULD be sent.
            client, svc, _ = _service(require_keys=False)
            params = svc.build_only(ot, symbol, side, qty, price, stop_price)
            signed_query = client.build_signed_query(params)
            console.print(Panel(
                json.dumps(params, indent=2),
                title="Payload (not sent)", border_style="yellow",
            ))
            console.print(Panel(
                signed_query.replace(signed_query.split("signature=")[-1], "<redacted>"),
                title="Signed query string", border_style="yellow",
            ))
            console.print("[yellow]Dry run — nothing was sent to Binance.[/]")
            return

        _, svc, _ = _service(require_keys=True)
        if ot == "MARKET":
            result = svc.place_market(symbol, side, qty)
        elif ot == "LIMIT":
            result = svc.place_limit(symbol, side, qty, price)
        elif ot == "STOP":
            result = svc.place_stop_limit(symbol, side, qty, price, stop_price)
        else:
            _fail(f"Unknown order type '{order_type}'. Use MARKET, LIMIT or STOP.")
            return
    except BotError as exc:
        _fail(str(exc))
        return

    _render_order_result(result)


def _render_order_result(result: dict) -> None:
    table = Table(title="Order Response", show_header=False, border_style="green")
    table.add_row("Order ID", str(result["orderId"]))
    table.add_row("Client ID", str(result["clientOrderId"]))
    table.add_row("Status", str(result["status"]))
    table.add_row("Executed Qty", str(result["executedQty"]))
    table.add_row("Avg Price", str(result["avgPrice"]))
    console.print(table)
    console.print(Panel("[bold green]✓ Order placed successfully[/]",
                        title="Success", border_style="green"))


@app.command()
def balance():
    """Show non-zero futures wallet balances."""
    try:
        client, _, _ = _service(require_keys=True)
        balances = client.get_balance()
    except BotError as exc:
        _fail(str(exc))
        return

    table = Table(title="Futures Balance", border_style="cyan")
    table.add_column("Asset")
    table.add_column("Balance", justify="right")
    table.add_column("Available", justify="right")
    for b in balances:
        if float(b.get("balance", 0)) != 0:
            table.add_row(b["asset"], b["balance"], b.get("availableBalance", "-"))
    console.print(table)


@app.command()
def price(symbol: str = typer.Argument(..., help="e.g. BTCUSDT")):
    """Show the latest mark/last price for a symbol."""
    try:
        client, _, _ = _service(require_keys=False)
        data = client.get_ticker_price(symbol.upper())
    except BotError as exc:
        _fail(str(exc))
        return
    console.print(Panel(f"[bold]{data['symbol']}[/] = [green]{data['price']}[/]",
                        title="Price", border_style="cyan"))


@app.command(name="exchange-info")
def exchange_info(symbol: str = typer.Argument(..., help="e.g. BTCUSDT")):
    """Show the trading filters (step/tick/min notional) for a symbol."""
    from bot import validators as v
    try:
        client, _, _ = _service(require_keys=False)
        info = client.get_exchange_info()
        filters = v.extract_symbol_filters(info, symbol.upper())
    except BotError as exc:
        _fail(str(exc))
        return
    table = Table(title=f"{symbol.upper()} Filters", show_header=False, border_style="cyan")
    for k, val in filters.items():
        table.add_row(k, str(val))
    console.print(table)


if __name__ == "__main__":
    app()
