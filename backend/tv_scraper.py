"""Parse TradingView websocket data for OHLCV candles.

The scraper captures websocket frames while repeatedly zooming out on the chart.
It stops when the earliest candle date stops improving for several rounds.
"""
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

TV_EXCHANGE = "NSEKE"
CACHE_DIR = Path(__file__).parent / "data" / "tv_prices"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def parse_tv_messages(messages: list[str]) -> list[dict]:
    """Extract OHLCV candles from TradingView websocket messages."""
    candles = []
    
    for msg in messages:
        # TradingView sends OHLCV in format: "v":[timestamp, open, high, low, close, volume]
        # Pattern: {"i":INDEX,"v":[TS,O,H,L,C,V]}
        matches = re.findall(
            r'"i"\s*:\s*\d+\s*,\s*"v"\s*:\s*\[\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]*)\s*)?\]',
            msg,
        )
        for m in matches:
            try:
                ts = float(m[0])
                if ts < 1e9 or ts > 2e9:
                    continue
                dt = datetime.utcfromtimestamp(ts).date()
                candles.append({
                    "date": dt.isoformat(),
                    "open": float(m[1]),
                    "high": float(m[2]),
                    "low": float(m[3]),
                    "close": float(m[4]),
                    "volume": int(float(m[5])) if m[5] else 0,
                })
            except (ValueError, IndexError):
                continue
    
    # Deduplicate by date while keeping the first parsed row per day.
    seen = set()
    unique = []
    for c in sorted(candles, key=lambda x: x["date"]):
        if c["date"] not in seen:
            seen.add(c["date"])
            unique.append(c)
    return unique


async def _zoom_out_round(page, steps: int = 12) -> bool:
    """Perform one zoom-out round to request older candles from TradingView."""
    chart = page.locator(".chart-markup-table").first
    if await chart.count() == 0:
        return False

    box = await chart.bounding_box()
    if not box:
        return False

    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    await page.mouse.move(cx, cy)
    for _ in range(steps):
        await page.keyboard.down("Control")
        await page.mouse.wheel(0, 200)
        await page.keyboard.up("Control")
        await asyncio.sleep(0.2)
    return True


async def fetch_tv_history(ticker: str, headless: bool = True) -> list[dict]:
    """Fetch historical daily OHLCV from TradingView via browser automation."""
    symbol = f"{TV_EXCHANGE}:{ticker}"
    url = f"https://www.tradingview.com/chart/?symbol={symbol}"
    
    all_messages: list[str] = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        def on_ws(ws):
            def on_frame(payload):
                if isinstance(payload, str):
                    all_messages.append(payload)

            ws.on("framereceived", lambda p: on_frame(p))
        
        page.on("websocket", on_ws)
        
        print(f"  Loading {symbol}...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        
        # Give TradingView time to establish websocket subscriptions.
        await asyncio.sleep(8)

        # Iteratively zoom out until earliest date stops moving.
        last_earliest = None
        stalled_rounds = 0
        max_rounds = 20

        for round_no in range(1, max_rounds + 1):
            try:
                did_zoom = await _zoom_out_round(page, steps=12)
                if not did_zoom:
                    print("  Could not find chart container for zooming.")
                    break

                await asyncio.sleep(2.5)

                snapshot = parse_tv_messages(all_messages)
                if not snapshot:
                    print(f"  Round {round_no}: no candles parsed yet")
                    continue

                earliest = snapshot[0]["date"]
                latest = snapshot[-1]["date"]
                print(f"  Round {round_no}: {len(snapshot)} candles ({earliest} -> {latest})")

                if earliest == last_earliest:
                    stalled_rounds += 1
                else:
                    stalled_rounds = 0
                    last_earliest = earliest

                if stalled_rounds >= 3:
                    print("  Earliest date stalled for 3 rounds. Stopping zoom loop.")
                    break
            except Exception as e:
                print(f"  Round {round_no} zoom error: {e}")
                break
        
        await browser.close()
    
    sizes = Counter("small" if len(m) < 1000 else "large" for m in all_messages)
    print(
        f"  Captured {len(all_messages)} messages "
        f"({sum(len(m) for m in all_messages)} bytes, "
        f"small={sizes.get('small', 0)}, large={sizes.get('large', 0)})"
    )
    candles = parse_tv_messages(all_messages)
    print(f"  Parsed {len(candles)} candles")
    if candles:
        print(f"  Range: {candles[0]['date']} to {candles[-1]['date']}")
    return candles


async def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "KCB"
    headless = "--headless" in sys.argv
    
    if ticker == "--all":
        from app.database import SessionLocal
        from app.models.company import Company
        db = SessionLocal()
        companies = db.query(Company).filter(Company.is_active == True).all()
        tickers = [c.ticker_symbol for c in companies]
        print(f"Fetching {len(tickers)} companies...")
        for i, t in enumerate(tickers):
            print(f"\n[{i+1}/{len(tickers)}] {t}")
            try:
                candles = await fetch_tv_history(t, headless=True)
                if candles:
                    with open(CACHE_DIR / f"{t}.json", "w") as f:
                        json.dump(candles, f)
                    print(f"  Saved {len(candles)} candles")
                await asyncio.sleep(3)
            except Exception as e:
                print(f"  ERROR: {e}")
    else:
        candles = await fetch_tv_history(ticker, headless=headless)
        if candles:
            with open(CACHE_DIR / f"{ticker}.json", "w") as f:
                json.dump(candles, f, indent=2)
            print(f"\nSaved to {CACHE_DIR / f'{ticker}.json'}")
        else:
            print("\nNo candles extracted. Dumping sample message for debug:")
            # Re-run and dump for debug
            pass


if __name__ == "__main__":
    asyncio.run(main())
