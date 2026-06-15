from __future__ import annotations

from moneyline.bookmakers.bangbet import BangBetAdapter
from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.bookmakers.betika import BetikaAdapter
from moneyline.bookmakers.betpawa import BetPawaAdapter
from moneyline.bookmakers.mozzartbet import MozzartBetAdapter
from moneyline.bookmakers.odibets import OdibetsAdapter
from moneyline.bookmakers.palmsbet import PalmsBetAdapter
from moneyline.bookmakers.pepeta import PepetaAdapter
from moneyline.bookmakers.probe import ProbeAdapter
from moneyline.bookmakers.shabiki import ShabikiAdapter
from moneyline.bookmakers.sportpesa import SportPesaAdapter
from moneyline.bookmakers.sportybet import SportyBetAdapter
from moneyline.models.schemas import Bookmaker

ADAPTERS: dict[Bookmaker, type[BookmakerAdapter]] = {
    Bookmaker.BETIKA: BetikaAdapter,
    Bookmaker.ODIBETS: OdibetsAdapter,
    Bookmaker.PEPETA: PepetaAdapter,
    Bookmaker.BANGBET: BangBetAdapter,
    Bookmaker.BETPAWA: BetPawaAdapter,
    Bookmaker.MOZZARTBET: MozzartBetAdapter,
    Bookmaker.SHABIKI: ShabikiAdapter,
    Bookmaker.SPORTYBET: SportyBetAdapter,
    Bookmaker.PALMSBET: PalmsBetAdapter,
    Bookmaker.SPORTPESA: SportPesaAdapter,
}

LIVE_BOOKMAKERS = {
    Bookmaker.BETIKA,
    Bookmaker.ODIBETS,
    Bookmaker.PEPETA,
    Bookmaker.BANGBET,
    Bookmaker.BETPAWA,
    Bookmaker.MOZZARTBET,
    Bookmaker.SHABIKI,
    Bookmaker.SPORTYBET,
    Bookmaker.PALMSBET,
    Bookmaker.SPORTPESA,
}


def get_adapter(bookmaker: Bookmaker) -> BookmakerAdapter:
    cls = ADAPTERS[bookmaker]
    if cls is ProbeAdapter:
        return ProbeAdapter(bookmaker)
    return cls()
