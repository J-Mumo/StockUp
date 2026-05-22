"""Marketscreener historical price adapter.

This adapter only works with a verified Marketscreener graphics URL that has
already been associated with a company. It does not guess quote identifiers.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import datetime, timezone

import requests
from playwright.async_api import async_playwright


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
        "&requestType=GET"
        "&src=itfp"
        f"&zb_key={history_key}"
        f"&token={token}"
    )


def _extract_iframe_url(html_content: str) -> str | None:
    matches = re.findall(
        r"https://light\.it-finance\.com/ZoneBoursePublic/itcharts\.phtml[^\"']+",
        html_content,
    )
    if not matches:
        return None
    return html.unescape(matches[0])


def _extract_application_settings(html_content: str) -> dict | None:
    match = re.search(
        r"var\s+application_settings\s*=\s*(\{.*?\})\s*;",
        html_content,
        re.DOTALL,
    )
    if not match:
        return None
    return json.loads(match.group(1))


def _parse_history_payload(payload: dict) -> list[dict]:
    if payload.get("s") != "ok":
        raise ValueError(f"Unexpected Marketscreener payload status: {payload.get('s')}")

    required = ["t", "o", "h", "l", "c", "v"]
    lengths = {key: len(payload.get(key, [])) for key in required}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"Mismatched payload lengths: {lengths}")

    candles = []
    for index, ts in enumerate(payload["t"]):
        close_price = float(payload["c"][index])
        if close_price <= 0:
            continue

        candles.append(
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
                "open": float(payload["o"][index]),
                "high": float(payload["h"][index]),
                "low": float(payload["l"][index]),
                "close": close_price,
                "volume": int(payload["v"][index] or 0),
            }
        )

    return candles


def candles_to_price_rows(candles: list[dict]) -> list[dict]:
    rows = []
    for candle in candles:
        rows.append(
            {
                "price_date": datetime.fromisoformat(candle["date"]).date(),
                "open_price": candle["open"],
                "high_price": candle["high"],
                "low_price": candle["low"],
                "close_price": candle["close"],
                "volume": candle.get("volume"),
                "source": "marketscreener",
            }
        )
    return rows


async def _fetch_history_via_playwright(context, history_url: str) -> str:
    history_page = await context.new_page()
    await history_page.goto(history_url, wait_until="domcontentloaded", timeout=45000)
    body_text = await history_page.text_content("body")
    await history_page.close()
    return body_text or ""


async def fetch_history(graphics_url: str, headless: bool = True) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Try plain HTTP first; fall back to Playwright if Marketscreener blocks us
    # (commonly with HTTP 403 from their bot protection).
    iframe_url = None
    settings = None
    graphics_html = None
    try:
        graphics_response = session.get(graphics_url, timeout=45)
        graphics_response.raise_for_status()
        graphics_html = graphics_response.text
        iframe_url = _extract_iframe_url(graphics_html)
        if iframe_url:
            iframe_response = session.get(iframe_url, timeout=45)
            iframe_response.raise_for_status()
            settings = _extract_application_settings(iframe_response.text)
    except requests.HTTPError as exc:
        # 403/429/etc — handled below via Playwright. Anything else, re-raise.
        if exc.response is None or exc.response.status_code not in (401, 403, 429):
            raise
        iframe_url = None
        settings = None

    async with async_playwright() as p:
        # Marketscreener's bot protection blocks headless Chromium with 403,
        # but accepts Firefox. Use Firefox for the browser-based fallback.
        browser = await p.firefox.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
        )

        if not iframe_url or not settings:
            page = await context.new_page()
            await page.goto(graphics_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(8)

            iframe_urls = await page.locator("iframe").evaluate_all(
                "nodes => nodes.map(node => node.src).filter(src => src && src.includes('light.it-finance.com/ZoneBoursePublic/itcharts.phtml'))"
            )
            if not iframe_urls:
                fallback_iframe = _extract_iframe_url(await page.content())
                iframe_urls = [fallback_iframe] if fallback_iframe else []

            if not iframe_urls:
                await browser.close()
                raise RuntimeError("Could not locate Marketscreener chart iframe")

            iframe_url = iframe_urls[0]
            iframe_page = await context.new_page()
            await iframe_page.goto(iframe_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(5)
            settings = await iframe_page.evaluate("() => window.application_settings")
            await iframe_page.close()

        if not settings:
            await browser.close()
            raise RuntimeError("Chart application settings were not available")

        instruments = settings.get("instruments") or []
        if not instruments:
            await browser.close()
            raise RuntimeError("No Marketscreener instruments were exposed by the chart app")

        history_url = _build_history_url(settings, instruments[0]["id"])

        # Copy cookies from Playwright context into the requests session so
        # the JSON history endpoint accepts our follow-up HTTP call. Without
        # this, Marketscreener's bot protection will return 403.
        try:
            for cookie in await context.cookies():
                session.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain"),
                    path=cookie.get("path", "/"),
                )
        except Exception:
            pass

        body_text = ""
        try:
            history_response = session.get(
                history_url,
                headers={"Referer": iframe_url},
                timeout=60,
            )
            history_response.raise_for_status()
            body_text = history_response.text
        except requests.RequestException:
            body_text = await _fetch_history_via_playwright(context, history_url)

        await browser.close()

    if not body_text:
        raise RuntimeError("Marketscreener history response body was empty")

    return _parse_history_payload(json.loads(body_text))


def fetch_history_sync(graphics_url: str, headless: bool = True) -> list[dict]:
    return asyncio.run(fetch_history(graphics_url, headless=headless))