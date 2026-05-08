"""Fetch historical daily OHLCV from a verified Marketscreener chart page.

Usage:
    python marketscreener_fetch.py KCB
    python marketscreener_fetch.py KCB https://www.marketscreener.com/quote/stock/KCB-GROUP-PLC-6493488/graphics/

The script needs a Marketscreener graphics page URL because the current schema
does not store Marketscreener identifiers for all companies.
"""

import json
import sys
from pathlib import Path

from app.data.marketscreener_adapter import fetch_history
from app.data.marketscreener_registry import VERIFIED_MARKETSCREENER_URLS


DEFAULT_GRAPHICS_URLS = VERIFIED_MARKETSCREENER_URLS

CACHE_DIR = Path(__file__).parent / "data" / "marketscreener_prices"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _build_history_url(settings: dict, instrument_id: int) -> str:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int(datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp())
    history_key = settings["zb_key"]["history"]["D"]
    token = settings["zb_t"]
    return (
        "https://www.zonebourse.com/mods_a/charts/TV/function/history"
        f"?from={start_ts}"
        f"&to={now_ts}"
        f"&symbol={instrument_id}"
        "&resolution=D"

    print(f"  Loading graphics page: {graphics_url}")
    candles = await fetch_history(graphics_url, headless=headless)
    if candles:
        print(f"  Parsed {len(candles)} candles")
        print(f"  Range: {candles[0]['date']} to {candles[-1]['date']}")
        output_path = CACHE_DIR / f"{ticker}.json"
        output_path.write_text(json.dumps(candles, indent=2), encoding="utf-8")
        print(f"Saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())