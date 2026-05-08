"""Auto-discover Marketscreener graphics URLs for NSE companies.

Uses Playwright to search Marketscreener for each company by name,
extract the stock page URL, and derive the graphics URL.

Usage:
    python discover_marketscreener.py                   # discover all companies
    python discover_marketscreener.py --ticker EQTY     # discover one company
    python discover_marketscreener.py --write           # save results to registry

Output is printed as a table. Nothing is written to the registry unless
--write is passed, and even then only confident matches are saved.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

# Allow running from backend/ root
sys.path.insert(0, str(Path(__file__).parent))

from app.data.marketscreener_registry import VERIFIED_MARKETSCREENER_URLS
from app.data.seed_data import NSE_COMPANIES

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

SEARCH_BASE = "https://www.marketscreener.com/search/?q={query}&mots=all"
GRAPHICS_SUFFIX = "/graphics/"


def _to_graphics_url(stock_url: str) -> str:
    """Convert any /quote/stock/.../ URL to a /graphics/ URL."""
    # Strip trailing path segments after the slug, keep up to the ID
    # e.g. /quote/stock/EQUITY-GROUP-HOLDINGS-6493490/financials/ -> .../graphics/
    match = re.match(r"(/quote/stock/[^/]+-\d+)/", stock_url)
    if match:
        return "https://www.marketscreener.com" + match.group(1) + GRAPHICS_SUFFIX
    return ""


async def search_one(browser_context, ticker: str, name: str) -> dict:
    """Search Marketscreener for a company and return the best URL match."""
    page = await browser_context.new_page()
    result = {"ticker": ticker, "name": name, "url": None, "confidence": "none"}
    try:
        query = name.replace("&", "and").replace(" Ltd", "").replace(" Plc", "").replace(" PLC", "").strip()
        search_url = SEARCH_BASE.format(query=query.replace(" ", "+"))
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

        # Wait a moment for JS content
        await page.wait_for_timeout(1500)
        content = await page.content()

        # Extract all /quote/stock/ links
        links = re.findall(r'/quote/stock/([A-Z0-9][^"\'<>]+?)-(\d+)/[^"\'<>\s]*', content, re.IGNORECASE)

        if not links:
            return result

        # Build candidate URLs
        candidates = []
        for slug, stock_id in links:
            candidates.append((slug, stock_id))

        # Remove duplicates while preserving order
        seen = set()
        unique = []
        for slug, stock_id in candidates:
            key = stock_id
            if key not in seen:
                seen.add(key)
                unique.append((slug, stock_id))

        if not unique:
            return result

        # Score candidates: prefer ones where ticker or name words appear in slug
        ticker_lower = ticker.lower().replace("-", "")
        name_words = {w.lower() for w in name.split() if len(w) > 2}

        def score(slug_id):
            slug, stock_id = slug_id
            slug_lower = slug.lower().replace("-", "")
            s = 0
            if ticker_lower in slug_lower:
                s += 10
            for word in name_words:
                if word in slug_lower:
                    s += 1
            return s

        unique.sort(key=score, reverse=True)
        best_slug, best_id = unique[0]
        best_score = score((best_slug, best_id))

        graphics_url = f"https://www.marketscreener.com/quote/stock/{best_slug}-{best_id}{GRAPHICS_SUFFIX}"
        result["url"] = graphics_url
        result["slug"] = best_slug
        result["id"] = best_id

        if best_score >= 10:
            result["confidence"] = "high"
        elif best_score >= 2:
            result["confidence"] = "medium"
        else:
            result["confidence"] = "low"

    except Exception as exc:
        result["error"] = str(exc)[:80]
    finally:
        await page.close()

    return result


async def discover(tickers: list[str], write: bool, headless: bool):
    from playwright.async_api import async_playwright

    companies = {c["ticker"]: c for c in NSE_COMPANIES}
    targets = []
    for t in tickers:
        if t not in companies:
            print(f"  Unknown ticker: {t}")
            continue
        targets.append(companies[t])

    if not targets:
        print("No companies to discover.")
        return

    print(f"Discovering {len(targets)} companies via Marketscreener search...")
    print(f"{'TICKER':<10} {'CONFIDENCE':<12} {'URL'}")
    print("-" * 90)

    found = {}
    skipped = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=USER_AGENT)
        await context.set_extra_http_headers({"Accept-Language": "en-US,en;q=0.9"})

        for company in targets:
            ticker = company["ticker"]

            # Skip if already in registry
            if ticker in VERIFIED_MARKETSCREENER_URLS:
                existing = VERIFIED_MARKETSCREENER_URLS[ticker]
                print(f"  {ticker:<8} {'[already set]':<12} {existing}")
                skipped.append(ticker)
                continue

            result = await search_one(context, ticker, company["name"])

            confidence = result.get("confidence", "none")
            url = result.get("url", "")
            error = result.get("error", "")

            if error:
                print(f"  {ticker:<8} {'ERROR':<12} {error}")
            elif url:
                flag = " *" if confidence == "low" else ""
                print(f"  {ticker:<8} {confidence:<12} {url}{flag}")
                if confidence in ("high", "medium"):
                    found[ticker] = url
            else:
                print(f"  {ticker:<8} {'not found':<12}")

            # Small delay to avoid hammering the server
            await asyncio.sleep(1.5)

        await context.close()
        await browser.close()

    print()
    print(f"Summary: {len(found)} candidates found, {len(skipped)} already in registry, "
          f"{len(targets) - len(found) - len(skipped)} not found or low confidence")

    if not found:
        return

    if write:
        _write_to_registry(found)
    else:
        print()
        print("Run with --write to save high/medium confidence results to the registry.")
        print("After writing, run:  python -m cli.commands sync-marketscreener-registry")


def _write_to_registry(new_entries: dict[str, str]):
    registry_path = Path(__file__).parent / "app" / "data" / "marketscreener_registry.py"
    content = registry_path.read_text(encoding="utf-8")

    # Merge with existing entries
    merged = dict(VERIFIED_MARKETSCREENER_URLS)
    merged.update(new_entries)

    lines = ['"""Verified Marketscreener graphics URLs for NSE companies.\n',
             "\n",
             "Only add entries here after confirming the page belongs to the exact company.\n",
             "This registry is intentionally explicit to avoid guessed identifiers.\n",
             '"""\n',
             "\n",
             "VERIFIED_MARKETSCREENER_URLS = {\n"]

    for ticker in sorted(merged):
        lines.append(f'    "{ticker}": "{merged[ticker]}",\n')

    lines.append("}\n")

    registry_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {len(merged)} entries to marketscreener_registry.py ({len(new_entries)} new).")


def main():
    parser = argparse.ArgumentParser(description="Discover Marketscreener URLs for NSE companies")
    parser.add_argument("--ticker", nargs="+", metavar="TICK",
                        help="Discover specific tickers only (default: all)")
    parser.add_argument("--write", action="store_true",
                        help="Write high/medium confidence results to the registry")
    parser.add_argument("--show-browser", action="store_true",
                        help="Run browser in visible mode (useful for debugging)")
    args = parser.parse_args()

    if args.ticker:
        tickers = [t.upper() for t in args.ticker]
    else:
        tickers = [c["ticker"] for c in NSE_COMPANIES]

    asyncio.run(discover(tickers, write=args.write, headless=not args.show_browser))


if __name__ == "__main__":
    main()
