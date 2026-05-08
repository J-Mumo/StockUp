"""Seed data for NSE market and companies.

Contains the full list of NSE-listed companies with their ticker symbols,
names, sectors, and yfinance ticker mappings.
"""

import logging
from sqlalchemy.orm import Session

from app.models.market import Market
from app.models.company import Company
from app.data.marketscreener_registry import VERIFIED_MARKETSCREENER_URLS

logger = logging.getLogger(__name__)

# NSE companies with afx.kwayisi.org tickers and yfinance mappings
# yfinance uses .NR suffix for Nairobi Securities Exchange
NSE_COMPANIES = [
    {"ticker": "ABSA", "name": "Absa Bank Kenya Plc", "sector": "Banking", "yf": "ABSA.NR"},
    {"ticker": "ALP", "name": "ALP Real Estate Investment Trust", "sector": "Real Estate", "yf": None},
    {"ticker": "AMAC", "name": "Africa Mega Agricorp", "sector": "Agriculture", "yf": None},
    {"ticker": "ARM", "name": "ARM Cement Ltd", "sector": "Manufacturing", "yf": "ARM.NR"},
    {"ticker": "BAMB", "name": "Bamburi Cement Ltd", "sector": "Manufacturing", "yf": "BAMB.NR"},
    {"ticker": "BAT", "name": "British American Tobacco Kenya", "sector": "Manufacturing", "yf": "BAT.NR"},
    {"ticker": "BKG", "name": "BK Group Plc", "sector": "Banking", "yf": "BKG.NR"},
    {"ticker": "BOC", "name": "BOC Kenya Ltd", "sector": "Manufacturing", "yf": "BOC.NR"},
    {"ticker": "BRIT", "name": "Britam Holdings Ltd", "sector": "Insurance", "yf": "BRIT.NR"},
    {"ticker": "CABL", "name": "East African Cables", "sector": "Manufacturing", "yf": "CABL.NR"},
    {"ticker": "CARB", "name": "Carbacid Investments", "sector": "Manufacturing", "yf": "CARB.NR"},
    {"ticker": "CGEN", "name": "Car and General Kenya Ltd", "sector": "Automobiles", "yf": "CGEN.NR"},
    {"ticker": "CIC", "name": "CIC Insurance Group Ltd", "sector": "Insurance", "yf": "CIC.NR"},
    {"ticker": "COOP", "name": "Co-operative Bank of Kenya", "sector": "Banking", "yf": "COOP.NR"},
    {"ticker": "CRWN", "name": "Crown Paints Kenya Ltd", "sector": "Manufacturing", "yf": "CRWN.NR"},
    {"ticker": "CTUM", "name": "Centum Investment Company", "sector": "Investment", "yf": "CTUM.NR"},
    {"ticker": "DCON", "name": "Deacons East Africa", "sector": "Retail", "yf": None},
    {"ticker": "DTK", "name": "Diamond Trust Bank Kenya Ltd", "sector": "Banking", "yf": "DTK.NR"},
    {"ticker": "EABL", "name": "East African Breweries Ltd", "sector": "Manufacturing", "yf": "EABL.NR"},
    {"ticker": "EGAD", "name": "Eaagads Ltd", "sector": "Agriculture", "yf": "EGAD.NR"},
    {"ticker": "EQTY", "name": "Equity Group Holdings Ltd", "sector": "Banking", "yf": "EQTY.NR"},
    {"ticker": "EVRD", "name": "Eveready East Africa Ltd", "sector": "Manufacturing", "yf": "EVRD.NR"},
    {"ticker": "FTGH", "name": "Flame Tree Group Holdings", "sector": "Manufacturing", "yf": "FTGH.NR"},
    {"ticker": "GLD", "name": "Absa NewGold ETF", "sector": "ETF", "yf": None},
    {"ticker": "HAFR", "name": "Home Afrika Ltd", "sector": "Real Estate", "yf": "HAFR.NR"},
    {"ticker": "HBE", "name": "Homeboyz Entertainment", "sector": "Media", "yf": None},
    {"ticker": "HFCK", "name": "HF Group Ltd", "sector": "Banking", "yf": "HFCK.NR"},
    {"ticker": "IMH", "name": "I&M Holdings Plc", "sector": "Banking", "yf": "IMH.NR"},
    {"ticker": "JUB", "name": "Jubilee Holdings Ltd", "sector": "Insurance", "yf": "JUB.NR"},
    {"ticker": "KAPC", "name": "Kapchorua Tea Company Ltd", "sector": "Agriculture", "yf": "KAPC.NR"},
    {"ticker": "KCB", "name": "KCB Group", "sector": "Banking", "yf": "KCB.NR"},
    {"ticker": "KEGN", "name": "KenGen Plc", "sector": "Energy", "yf": "KEGN.NR"},
    {"ticker": "KNRE", "name": "Kenya Re-Insurance Corporation", "sector": "Insurance", "yf": "KNRE.NR"},
    {"ticker": "KPC", "name": "Kenya Pipeline Company", "sector": "Energy", "yf": None},
    {"ticker": "KPLC", "name": "Kenya Power & Lighting Company", "sector": "Energy", "yf": "KPLC.NR"},
    {"ticker": "KPLC-P4", "name": "Kenya Power 4% Preference Shares", "sector": "Energy", "yf": None},
    {"ticker": "KPLC-P7", "name": "Kenya Power 7% Preference Shares", "sector": "Energy", "yf": None},
    {"ticker": "KQ", "name": "Kenya Airways Ltd", "sector": "Transport", "yf": "KQ.NR"},
    {"ticker": "KUKZ", "name": "Kakuzi Ltd", "sector": "Agriculture", "yf": "KUKZ.NR"},
    {"ticker": "KURV", "name": "Kurwitu Ventures Ltd", "sector": "Investment", "yf": None},
    {"ticker": "LAPR", "name": "Laptrust Imara Income-REIT", "sector": "Real Estate", "yf": None},
    {"ticker": "LBTY", "name": "Liberty Kenya Holdings Ltd", "sector": "Insurance", "yf": "LBTY.NR"},
    {"ticker": "LIMT", "name": "Limuru Tea Company Ltd", "sector": "Agriculture", "yf": "LIMT.NR"},
    {"ticker": "LKL", "name": "Longhorn Publishers Ltd", "sector": "Media", "yf": "LKL.NR"},
    {"ticker": "MSC", "name": "Mumias Sugar Company Ltd", "sector": "Agriculture", "yf": None},
    {"ticker": "NBV", "name": "Nairobi Business Ventures Ltd", "sector": "Investment", "yf": "NBV.NR"},
    {"ticker": "NCBA", "name": "NCBA Group Plc", "sector": "Banking", "yf": "NCBA.NR"},
    {"ticker": "NMG", "name": "Nation Media Group", "sector": "Media", "yf": "NMG.NR"},
    {"ticker": "NSE", "name": "Nairobi Securities Exchange Ltd", "sector": "Financial Services", "yf": "NSE.NR"},
    {"ticker": "OCH", "name": "Olympia Capital Holdings Ltd", "sector": "Investment", "yf": "OCH.NR"},
    {"ticker": "PORT", "name": "East African Portland Cement", "sector": "Manufacturing", "yf": "PORT.NR"},
    {"ticker": "SASN", "name": "Sasini Tea and Coffee Ltd", "sector": "Agriculture", "yf": "SASN.NR"},
    {"ticker": "SBIC", "name": "Stanbic Holdings Ltd", "sector": "Banking", "yf": "SBIC.NR"},
    {"ticker": "SCAN", "name": "ScanGroup Ltd", "sector": "Media", "yf": "SCAN.NR"},
    {"ticker": "SCBK", "name": "Standard Chartered Bank Ltd", "sector": "Banking", "yf": "SCBK.NR"},
    {"ticker": "SCOM", "name": "Safaricom Plc", "sector": "Telecommunications", "yf": "SCOM.NR"},
    {"ticker": "SGL", "name": "Standard Group Ltd", "sector": "Media", "yf": "SGL.NR"},
    {"ticker": "SKL", "name": "Shri Krishana Overseas Ltd", "sector": "Manufacturing", "yf": None},
    {"ticker": "SLAM", "name": "Sanlam Kenya Plc", "sector": "Insurance", "yf": "SLAM.NR"},
    {"ticker": "SMER", "name": "Sameer Africa Plc", "sector": "Manufacturing", "yf": "SMER.NR"},
    {"ticker": "SMWF", "name": "Satrix MSCI World Feeder ETF", "sector": "ETF", "yf": None},
    {"ticker": "TCL", "name": "TransCentury Plc", "sector": "Investment", "yf": "TCL.NR"},
    {"ticker": "TOTL", "name": "Total Kenya Ltd", "sector": "Energy", "yf": "TOTL.NR"},
    {"ticker": "TPSE", "name": "TPS Eastern Africa Serena Ltd", "sector": "Hospitality", "yf": "TPSE.NR"},
    {"ticker": "UCHM", "name": "Uchumi Supermarket Ltd", "sector": "Retail", "yf": "UCHM.NR"},
    {"ticker": "UMME", "name": "Umeme Ltd", "sector": "Energy", "yf": "UMME.NR"},
    {"ticker": "UNGA", "name": "Unga Group Ltd", "sector": "Manufacturing", "yf": "UNGA.NR"},
    {"ticker": "WTK", "name": "Williamson Tea Kenya Ltd", "sector": "Agriculture", "yf": "WTK.NR"},
    {"ticker": "XPRS", "name": "Express Kenya Ltd", "sector": "Transport", "yf": "XPRS.NR"},
]


def seed_nse_market_and_companies(db: Session) -> dict:
    """Seed the NSE market and all listed companies.
    
    Returns dict with counts of created/existing items.
    """
    stats = {"market": "existing", "companies_created": 0, "companies_existing": 0}

    # Create or get NSE market
    market = db.query(Market).filter(Market.code == "NSE").first()
    if not market:
        market = Market(
            name="Nairobi Securities Exchange",
            code="NSE",
            country="Kenya",
            currency="KES",
            is_active=True,
        )
        db.add(market)
        db.flush()
        stats["market"] = "created"
        logger.info("Created NSE market")

    # Seed companies
    for company_data in NSE_COMPANIES:
        existing = db.query(Company).filter(
            Company.ticker_symbol == company_data["ticker"]
        ).first()

        if existing:
            ms_url = VERIFIED_MARKETSCREENER_URLS.get(company_data["ticker"])
            if ms_url and not existing.marketscreener_graphics_url:
                existing.marketscreener_graphics_url = ms_url
            stats["companies_existing"] += 1
            continue

        company = Company(
            market_id=market.id,
            name=company_data["name"],
            ticker_symbol=company_data["ticker"],
            yfinance_ticker=company_data["yf"],
            sector=company_data["sector"],
            marketscreener_graphics_url=VERIFIED_MARKETSCREENER_URLS.get(company_data["ticker"]),
            is_active=True,
        )
        db.add(company)
        stats["companies_created"] += 1
        logger.info(f"Created company: {company_data['ticker']} - {company_data['name']}")

    db.commit()
    logger.info(
        f"Seed complete: market={stats['market']}, "
        f"companies created={stats['companies_created']}, "
        f"existing={stats['companies_existing']}"
    )
    return stats
