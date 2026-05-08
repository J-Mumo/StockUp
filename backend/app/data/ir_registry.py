"""Investor Relations URL registry for NSE-listed companies.

Maps each company ticker to its investor relations page URL and annual
report PDF discovery strategy. Used by the PDF downloader to locate
and fetch audited annual reports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class IREntry:
    """Investor relations metadata for a single company."""

    ir_url: str = ""
    """Base investor relations page URL."""

    report_url_pattern: str = ""
    """Direct URL pattern for annual report PDFs.
    Supports {year} placeholder, e.g.:
    https://example.com/reports/annual-report-{year}.pdf
    """

    search_domain: str = ""
    """Company domain for Google search fallback."""

    notes: str = ""
    """Any notes about the company's IR page or reporting patterns."""


# ---------------------------------------------------------------------------
# Registry of all 69 NSE-listed companies
# ---------------------------------------------------------------------------
# Sources:
# - Company websites and investor relations pages
# - CMA Kenya filings
# - NSE website: https://www.nse.co.ke/listed-companies/
#
# For companies without known direct PDF URLs, we rely on the LLM-assisted
# search strategy (ask GPT to find the PDF URL given the company name + year).
# ---------------------------------------------------------------------------

IR_REGISTRY: dict[str, IREntry] = {
    # --- Banking ---
    "ABSA": IREntry(
        ir_url="https://www.absabank.co.ke/investor-relations/",
        search_domain="absabank.co.ke",
    ),
    "BKG": IREntry(
        ir_url="https://bfrgroup.co.ke/investor-relations/",
        search_domain="bfrgroup.co.ke",
        notes="BK Group (formerly I&M Holdings Rwanda unit)",
    ),
    "COOP": IREntry(
        ir_url="https://www.co-opbank.co.ke/investor-relations/",
        search_domain="co-opbank.co.ke",
    ),
    "DTK": IREntry(
        ir_url="https://dtbafrica.com/investor-relations/",
        search_domain="dtbafrica.com",
        notes="Diamond Trust Bank Kenya",
    ),
    "EQTY": IREntry(
        ir_url="https://equitygroupholdings.com/investor-relations/",
        search_domain="equitygroupholdings.com",
    ),
    "HFCK": IREntry(
        ir_url="https://www.hfrgroup.co.ke/investor-relations/",
        search_domain="hfrgroup.co.ke",
        notes="HF Group (formerly Housing Finance)",
    ),
    "IMH": IREntry(
        ir_url="https://www.imgroup.co.ke/investor-relations/",
        search_domain="imgroup.co.ke",
        notes="I&M Holdings",
    ),
    "KCB": IREntry(
        ir_url="https://kcbgroup.com/investor-relations/",
        search_domain="kcbgroup.com",
    ),
    "NBK": IREntry(
        ir_url="https://www.nationalbank.co.ke/investor-relations/",
        search_domain="nationalbank.co.ke",
        notes="National Bank of Kenya (KCB Group subsidiary)",
    ),
    "NIC": IREntry(
        ir_url="https://www.ncbagroup.com/investor-relations/",
        search_domain="ncbagroup.com",
        notes="NCBA Group (formerly NIC Bank + CBA merger)",
    ),
    "SBIC": IREntry(
        ir_url="https://www.stanbicbank.co.ke/investor-relations/",
        search_domain="stanbicbank.co.ke",
        notes="Stanbic Holdings Kenya",
    ),
    "SCBK": IREntry(
        ir_url="https://www.sc.com/ke/investor-relations/",
        search_domain="sc.com",
        notes="Standard Chartered Bank Kenya",
    ),

    # --- Insurance ---
    "BRIT": IREntry(
        ir_url="https://www.britam.com/investor-relations/",
        search_domain="britam.com",
    ),
    "CIC": IREntry(
        ir_url="https://www.cic.co.ke/investor-relations/",
        search_domain="cic.co.ke",
    ),
    "JUB": IREntry(
        ir_url="https://www.jubileeinsurance.com/investor-relations/",
        search_domain="jubileeinsurance.com",
    ),
    "KNRE": IREntry(
        ir_url="https://www.kenyare.co.ke/",
        search_domain="kenyare.co.ke",
        notes="Kenya Reinsurance Corporation",
    ),
    "LBTY": IREntry(
        ir_url="https://www.libertykenya.co.ke/",
        search_domain="libertykenya.co.ke",
    ),

    # --- Telecom ---
    "SCOM": IREntry(
        ir_url="https://www.safaricom.co.ke/about/investor-relations/",
        search_domain="safaricom.co.ke",
    ),

    # --- Energy ---
    "KEGN": IREntry(
        ir_url="https://www.kengen.co.ke/investor-relations/",
        search_domain="kengen.co.ke",
    ),
    "KPLC": IREntry(
        ir_url="https://www.kplc.co.ke/content/item/58/investor-relations",
        search_domain="kplc.co.ke",
    ),
    "TOTL": IREntry(
        ir_url="https://www.totalenergies.co.ke/",
        search_domain="totalenergies.co.ke",
        notes="TotalEnergies Marketing Kenya",
    ),
    "UMME": IREntry(
        ir_url="https://www.umeme.co.ug/investor-relations/",
        search_domain="umeme.co.ug",
    ),

    # --- Manufacturing ---
    "BAMB": IREntry(
        ir_url="https://www.bamburi.co.ke/",
        search_domain="bamburi.co.ke",
        notes="Bamburi Cement",
    ),
    "BAT": IREntry(
        ir_url="https://www.bat.com/kenya",
        search_domain="bat.com",
        notes="British American Tobacco Kenya",
    ),
    "BOC": IREntry(
        ir_url="https://www.bocindustrial.co.ke/",
        search_domain="bocindustrial.co.ke",
        notes="BOC Gases Kenya",
    ),
    "CARB": IREntry(
        ir_url="https://carbacid.co.ke/",
        search_domain="carbacid.co.ke",
    ),
    "EABL": IREntry(
        ir_url="https://www.eabl.com/investor-centre/",
        search_domain="eabl.com",
        notes="East African Breweries",
    ),
    "FIRE": IREntry(
        ir_url="https://www.firestoneea.com/",
        search_domain="firestoneea.com",
    ),
    "SMER": IREntry(
        ir_url="https://www.sameer.co.ke/",
        search_domain="sameer.co.ke",
        notes="Sameer Africa",
    ),
    "UNGA": IREntry(
        ir_url="https://www.unga.com/",
        search_domain="unga.com",
        notes="Unga Group",
    ),

    # --- Agriculture ---
    "EGAD": IREntry(
        ir_url="https://www.eaagads.co.ke/",
        search_domain="eaagads.co.ke",
        notes="Eaagads Limited",
    ),
    "KAKZ": IREntry(
        ir_url="",
        search_domain="",
        notes="Kakuzi Plc",
    ),
    "LIMT": IREntry(
        ir_url="https://www.limuru-tea.com",
        search_domain="limuru-tea.com",
        notes="Limuru Tea Company",
    ),
    "SASN": IREntry(
        ir_url="https://www.sasini.co.ke/",
        search_domain="sasini.co.ke",
    ),
    "WTK": IREntry(
        ir_url="https://www.williamsontea.com/",
        search_domain="williamsontea.com",
        notes="Williamson Tea Kenya",
    ),

    # --- Real Estate / Construction ---
    "CTDL": IREntry(
        ir_url="https://www.centum.co.ke/investor-relations/",
        search_domain="centum.co.ke",
        notes="Centum Investment Co (formerly ICDC)",
    ),
    "HOME": IREntry(
        ir_url="https://www.homeafrika.com/",
        search_domain="homeafrika.com",
    ),

    # --- Automotive ---
    "MASH": IREntry(
        ir_url="https://www.marshalls.co.ke/",
        search_domain="marshalls.co.ke",
        notes="Marshalls East Africa",
    ),

    # --- Investment ---
    "CABL": IREntry(
        ir_url="https://www.eacables.com/",
        search_domain="eacables.com",
        notes="East African Cables",
    ),
    "HAFR": IREntry(
        ir_url="https://www.ha.co.ke/",
        search_domain="ha.co.ke",
        notes="Home Afrika",
    ),
    "KURV": IREntry(
        ir_url="",
        search_domain="",
        notes="Kurv (formerly Flame Tree Group)",
    ),
    "LKL": IREntry(
        ir_url="https://www.longhornpublishers.com/",
        search_domain="longhornpublishers.com",
        notes="Longhorn Publishers",
    ),
    "MSC": IREntry(
        ir_url="",
        search_domain="",
        notes="Nairobi Securities Exchange Plc",
    ),
    "OCH": IREntry(
        ir_url="",
        search_domain="",
        notes="Olympia Capital Holdings",
    ),
    "PORT": IREntry(
        ir_url="",
        search_domain="",
        notes="East African Portland Cement",
    ),
    "SCAN": IREntry(
        ir_url="https://www.scangroup.biz/",
        search_domain="scangroup.biz",
        notes="WPP Scangroup",
    ),
    "SGL": IREntry(
        ir_url="",
        search_domain="",
        notes="Standard Group",
    ),
    "TCL": IREntry(
        ir_url="https://www.transcentury.co.ke/",
        search_domain="transcentury.co.ke",
    ),
    "TPSE": IREntry(
        ir_url="https://www.serenahotels.com/",
        search_domain="serenahotels.com",
        notes="TPS Eastern Africa / Serena Hotels",
    ),
    "UCHM": IREntry(
        ir_url="",
        search_domain="",
        notes="Uchumi Supermarket (may be delisted/inactive)",
    ),
    "XPRS": IREntry(
        ir_url="",
        search_domain="",
        notes="Express Kenya",
    ),

    # --- ETFs ---
    "ABSP": IREntry(notes="ABSA NewGold ETF"),
    "SMWF": IREntry(notes="Satrix MSCI World Feeder ETF"),

    # --- Other ---
    "CFCI": IREntry(
        ir_url="",
        search_domain="",
        notes="Car & General (K) Ltd",
    ),
    "DCON": IREntry(
        ir_url="",
        search_domain="",
        notes="Deacons East Africa",
    ),
    "EVRD": IREntry(
        ir_url="",
        search_domain="",
        notes="Eveready East Africa",
    ),
    "GWS": IREntry(
        ir_url="",
        search_domain="",
        notes="George Williamson Kenya (subsidiary of WTK)",
    ),
    "HAFR": IREntry(
        ir_url="https://www.homeafrika.com/",
        search_domain="homeafrika.com",
    ),
    "KQ": IREntry(
        ir_url="https://www.kqcorporate.com/index.php/investor-relations",
        search_domain="kqcorporate.com",
        notes="Kenya Airways",
    ),
    "NATN": IREntry(
        ir_url="https://www.nationmedia.com/investors/",
        search_domain="nationmedia.com",
        notes="Nation Media Group",
    ),
    "NCBA": IREntry(
        ir_url="https://www.ncbagroup.com/investor-relations/",
        search_domain="ncbagroup.com",
        notes="Alias for NIC — NCBA Group",
    ),
    "NSE": IREntry(
        ir_url="https://www.nse.co.ke/investor-relations/",
        search_domain="nse.co.ke",
        notes="Nairobi Securities Exchange Plc (self-listed)",
    ),
    "STAD": IREntry(
        ir_url="",
        search_domain="",
        notes="East Africa Cables",
    ),
}


def get_ir_entry(ticker: str) -> IREntry:
    """Get the IR registry entry for a company, or a blank fallback."""
    return IR_REGISTRY.get(ticker.upper(), IREntry())


def get_all_tickers_with_ir() -> list[str]:
    """Return tickers that have at least an IR URL or search domain."""
    return [
        ticker
        for ticker, entry in IR_REGISTRY.items()
        if entry.ir_url or entry.search_domain
    ]
