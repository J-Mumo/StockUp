"""Local price updater — runs on the operator's Windows machine.

Marketscreener's Akamai bot protection returns HTTP 403 to the Hetzner VM's
IP range, so daily price ingestion is done from a residential IP instead of
the server. This script:

  1. Fetches the list of companies with a Marketscreener graphics URL from
     the server (`GET /api/internal/companies-with-ms-url`).
  2. For each company, fetches full daily history via the existing
     `marketscreener_adapter` (Playwright Firefox).
  3. Filters the candles to the trailing `--days` window (default: 14).
  4. Posts them to `POST /api/internal/prices/upsert`.

Configuration (env vars, .env in this script's directory, or CLI):

    STOCKUP_API_BASE      Base URL, e.g. https://stockup.jmumo.com
    INTERNAL_API_TOKEN    Shared secret matching the server setting

Usage (from repo root, with the backend venv active):

    python -m backend.scripts.local_price_updater --days 14

    # Or dry-run against one ticker (no POST):
    python -m backend.scripts.local_price_updater --ticker SCOM --days 30 --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Make sure we can import `app.*` when run as a script
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.data import marketscreener_adapter  # noqa: E402


def _log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _load_env() -> tuple[str, str]:
    # Prefer a local .env next to this script; fall back to the backend .env
    here = Path(__file__).resolve().parent
    for candidate in (here / ".env", here / ".env.local", _BACKEND_DIR / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
    api_base = os.getenv("STOCKUP_API_BASE", "").rstrip("/")
    token = os.getenv("INTERNAL_API_TOKEN", "")
    if not api_base or not token:
        _log("ERROR: STOCKUP_API_BASE and INTERNAL_API_TOKEN must be set.")
        sys.exit(2)
    return api_base, token


def _list_companies(api_base: str, token: str, ticker: Optional[str]) -> list[dict]:
    resp = requests.get(
        f"{api_base}/api/internal/companies-with-ms-url",
        headers={"X-Internal-Token": token},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json()
    if ticker:
        items = [c for c in items if c["ticker"].upper() == ticker.upper()]
    return items


def _upsert(
    api_base: str,
    token: str,
    ticker: str,
    candles: list[dict],
) -> dict:
    payload = {
        "ticker": ticker,
        "source": "marketscreener",
        "candles": [
            {
                "date": c["date"],
                "open": c.get("open"),
                "high": c.get("high"),
                "low": c.get("low"),
                "close": c["close"],
                "volume": c.get("volume"),
            }
            for c in candles
        ],
    }
    resp = requests.post(
        f"{api_base}/api/internal/prices/upsert",
        json=payload,
        headers={"X-Internal-Token": token},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _filter_recent(candles: list[dict], days: int) -> list[dict]:
    if days <= 0:
        return candles
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [c for c in candles if c["date"] >= cutoff]


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Marketscreener price updater")
    parser.add_argument("--days", type=int, default=14, help="Trailing window in days (0 = full history)")
    parser.add_argument("--ticker", help="Only process this single ticker (case-insensitive)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and log, but don't POST")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds between companies (be polite)")
    args = parser.parse_args()

    api_base, token = _load_env()
    _log(f"API base: {api_base}")

    try:
        companies = _list_companies(api_base, token, args.ticker)
    except requests.RequestException as e:
        _log(f"ERROR fetching company list: {e}")
        return 1
    _log(f"Companies to process: {len(companies)}")

    stats = {"fetched": 0, "no_candles": 0, "posted": 0, "upserted": 0, "failed": 0}
    for i, c in enumerate(companies, start=1):
        ticker = c["ticker"]
        url = c["marketscreener_graphics_url"]
        _log(f"[{i}/{len(companies)}] {ticker} → fetching …")
        try:
            candles = marketscreener_adapter.fetch_history_sync(url)
        except Exception as e:
            stats["failed"] += 1
            _log(f"  ! fetch failed: {e}")
            time.sleep(args.sleep)
            continue

        stats["fetched"] += 1
        recent = _filter_recent(candles, args.days)
        if not recent:
            stats["no_candles"] += 1
            _log(f"  · no candles in trailing {args.days}d window (total: {len(candles)})")
            time.sleep(args.sleep)
            continue

        latest = recent[-1]
        _log(f"  · {len(recent)} candles, latest {latest['date']} close={latest['close']}")

        if args.dry_run:
            time.sleep(args.sleep)
            continue

        try:
            result = _upsert(api_base, token, ticker, recent)
            stats["posted"] += 1
            stats["upserted"] += result.get("upserted", 0)
            _log(f"  ✓ upserted {result.get('upserted')} of {result.get('received')}")
        except requests.RequestException as e:
            stats["failed"] += 1
            body = getattr(e.response, "text", "") if getattr(e, "response", None) else ""
            _log(f"  ! POST failed: {e} {body[:200]}")

        time.sleep(args.sleep)

    _log(
        "DONE — fetched={fetched} posted={posted} upserted={upserted} "
        "no_candles={no_candles} failed={failed}".format(**stats)
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
