"""Sector classification — maps free-form ``Company.sector`` strings to a
canonical ``SectorKind`` used by the dispatcher."""

from __future__ import annotations

from enum import Enum


class SectorKind(str, Enum):
    BANK = "bank"
    INSURANCE = "insurance"
    REIT = "reit"
    INDUSTRIAL = "industrial"


# Case-insensitive keyword matching. First match wins.
_KEYWORDS: list[tuple[SectorKind, tuple[str, ...]]] = [
    (SectorKind.BANK, ("bank", "banking", "financial services")),
    (SectorKind.INSURANCE, ("insurance", "insurer", "reinsurance")),
    (SectorKind.REIT, ("reit", "real estate investment trust")),
]


def classify_sector(sector: str | None) -> SectorKind:
    """Return the canonical sector kind for a company.

    Unknown or missing sectors default to ``INDUSTRIAL`` so the existing
    DCF/EPV/BV pipeline runs — never crashes.
    """
    if not sector:
        return SectorKind.INDUSTRIAL
    normalised = sector.strip().lower()
    for kind, keywords in _KEYWORDS:
        for kw in keywords:
            if kw in normalised:
                return kind
    return SectorKind.INDUSTRIAL
