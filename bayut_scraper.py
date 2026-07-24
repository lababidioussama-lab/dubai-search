"""
Bayut Scraper Engine — smart extraction + professional Excel report.

Key upgrades over the original version:
  - Extracts data from Bayut's embedded __NEXT_DATA__ JSON (the same data
    the page itself renders from) instead of fragile whole-page regex.
    This fixes the classic bugs: bathrooms always showing "253", location
    resolving to "DAMAC Hills Villas/Townhouses" instead of the real
    sub-community, trailing commas in price, and duplicated permit numbers
    picked up from an unrelated part of the page.
  - Falls back to scoped regex (inside the property info card only, never
    the whole HTML) if JSON extraction fails for a given page.
  - Adds richer, cleaner fields: City / Community / Sub-Community / Tower,
    Completion Status, Furnishing, Agency, Agent Phone, Reference Number,
    Price per sqft, Value Rating, Listed Date, Latitude/Longitude, Cover
    Photo URL.
  - Numeric columns are stored as real numbers (int/float), not strings,
    so Excel can sort/filter/sum them.
  - Retries failed page loads and logs failures instead of silently
    dropping listings.
  - Structured logging (console + optional log file) instead of ad-hoc
    prints for operational status.
  - Three-sheet Excel workbook: a Cover page with search criteria, a
    Dashboard with KPI tiles and charts, and a styled Listings table with
    conditional-formatting color scale, banded rows, autofilter, frozen
    header, and clickable URL hyperlinks.
"""

import time
import re
import json
import random
import os
import sys
import logging
import difflib
import argparse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.chart import BarChart, PieChart, Reference
from DrissionPage import ChromiumPage, ChromiumOptions

__version__ = "2.0.0"

# ==========================================
# TERMINAL COLOR & LOGO CONFIGURATION
# ==========================================
GREEN = "\033[92m"
RESET = "\033[0m"

BRAND_NAVY = "1F4E78"
BRAND_BLUE = "2E75B6"
BRAND_GOLD = "C9A227"
BRAND_LIGHT = "F2F6FC"


def print_logo() -> None:
    logo = f"""{GREEN}
██████╗  █████╗ ██╗   ██╗██╗   ██╗████████╗    ███████╗ ██████╗██████╗  █████╗ ██████╗ ███████╗██████╗
██╔══██╗██╔══██╗╚██╗ ██╔╝██║   ██║╚══██╔══╝    ██╔════╝██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
██████╔╝███████║ ╚████╔╝ ██║   ██║   ██║       ███████╗██║     ██████╔╝███████║██████╔╝█████╗  ██████╔╝
██╔══██╗██╔══██║  ╚██╔╝  ██║   ██║   ██║       ╚╚════██║██║     ██╔══██╗██╔══██║██╔═══╝ ██╔══╝  ██╔══██╗
██████╔╝███████║   ██║   ╚██████╔╝   ██║       ███████║╚██████╗██║  ██║██║  ██║██║     ███████╗██║  ██║
╚═════╝ ╚══════╝   ╚═╝    ╚═════╝    ╚═╝       ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝

                 [ B U I L T   B Y   O U S S A M A ]           v{__version__}
{RESET}"""
    print(logo)


def cprint(text: str) -> None:
    print(f"{GREEN}{text}{RESET}")


# ==========================================
# LOGGING
# ==========================================
class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[90m",
        logging.INFO: "\033[92m",
        logging.WARNING: "\033[93m",
        logging.ERROR: "\033[91m",
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        return f"{color}{super().format(record)}{RESET}"


def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger("bayut_scraper")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ColorFormatter("%(message)s"))
    logger.addHandler(console)

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(file_handler)

    return logger


logger = logging.getLogger("bayut_scraper")


# ==========================================
# ULTIMATE & EXHAUSTIVE DUBAI FULL PROJECT DATABASE
# Covers master-communities, sub-communities/clusters, and individual
# towers/buildings so free-text input resolves to an exact Bayut slug
# instead of falling through to fuzzy-matching or a raw slugified guess.
# ==========================================
LOCATION_DATABASE: Dict[str, str] = {
    # ---- DAMAC Lagoons (sub-communities) ----
    "santorini": "dubai/damac-lagoons/santorini",
    "damac lagoons santorini": "dubai/damac-lagoons/santorini",
    "malta": "dubai/damac-lagoons/malta",
    "damac lagoons malta": "dubai/damac-lagoons/malta",
    "venice": "dubai/damac-lagoons/venice",
    "damac lagoons venice": "dubai/damac-lagoons/venice",
    "portofino": "dubai/damac-lagoons/portofino",
    "damac lagoons portofino": "dubai/damac-lagoons/portofino",
    "costa brava": "dubai/damac-lagoons/costa-brava",
    "damac lagoons costa brava": "dubai/damac-lagoons/costa-brava",
    "nice": "dubai/damac-lagoons/nice",
    "damac lagoons nice": "dubai/damac-lagoons/nice",
    "marbella": "dubai/damac-lagoons/marbella",
    "damac lagoons marbella": "dubai/damac-lagoons/marbella",
    "morocco": "dubai/damac-lagoons/morocco",
    "damac lagoons morocco": "dubai/damac-lagoons/morocco",
    "monte carlo": "dubai/damac-lagoons/monte-carlo",
    "damac lagoons monte carlo": "dubai/damac-lagoons/monte-carlo",
    "ibiza": "dubai/damac-lagoons/ibiza",
    "damac lagoons ibiza": "dubai/damac-lagoons/ibiza",
    "cote d azur": "dubai/damac-lagoons/cote-d-azur",
    "damac lagoons cote d azur": "dubai/damac-lagoons/cote-d-azur",
    "damac lagoons": "dubai/damac-lagoons",

    # ---- DAMAC Hills / DAMAC Hills 2 (sub-communities & clusters) ----
    "damac hills": "dubai/damac-hills",
    "damac hills 2": "dubai/damac-hills-2",
    "akoya": "dubai/damac-hills-2",
    "akoya oxygen": "dubai/damac-hills-2",
    "the drive": "dubai/damac-hills/the-drive",
    "damac hills the drive": "dubai/damac-hills/the-drive",
    "golf town": "dubai/damac-hills/golf-town",
    "damac hills golf town": "dubai/damac-hills/golf-town",
    "the park": "dubai/damac-hills/the-park",
    "damac hills the park": "dubai/damac-hills/the-park",
    "carson": "dubai/damac-hills/carson",
    "damac hills carson": "dubai/damac-hills/carson",
    "mira": "dubai/reem/mira",
    "trump estates": "dubai/damac-hills/trump-estates",
    "damac hills trump estates": "dubai/damac-hills/trump-estates",
    "veneto": "dubai/damac-hills/veneto",
    "damac hills veneto": "dubai/damac-hills/veneto",
    "artesia": "dubai/damac-hills/artesia",
    "damac hills artesia": "dubai/damac-hills/artesia",
    "safa one": "dubai/al-safa/safa-one",
    "damac towers": "dubai/business-bay/damac-towers-by-paramount",
    "damac maison": "dubai/business-bay/damac-maison",

    # ---- Jumeirah Village Circle (JVC) ----
    "jumeirah village circle": "dubai/jumeirah-village-circle",
    "jvc": "dubai/jumeirah-village-circle",
    "jumeirah village triangle": "dubai/jumeirah-village-triangle",
    "jvt": "dubai/jumeirah-village-triangle",

    # ---- Dubai Marina & towers ----
    "dubai marina": "dubai/dubai-marina",
    "marina": "dubai/dubai-marina",
    "marina gate": "dubai/dubai-marina/marina-gate",
    "marina pinnacle": "dubai/dubai-marina/marina-pinnacle",
    "cayan tower": "dubai/dubai-marina/cayan-tower",
    "princess tower": "dubai/dubai-marina/princess-tower",
    "elite residence": "dubai/dubai-marina/elite-residence",
    "marina crown": "dubai/dubai-marina/marina-crown",
    "the address dubai marina": "dubai/dubai-marina/the-address-dubai-marina",
    "emaar 6 towers": "dubai/dubai-marina/emaar-6-towers",
    "jumeirah beach residence": "dubai/jumeirah-beach-residence-jbr",
    "jbr": "dubai/jumeirah-beach-residence-jbr",

    # ---- Downtown Dubai ----
    "downtown dubai": "dubai/downtown-dubai",
    "downtown": "dubai/downtown-dubai",
    "burj khalifa": "dubai/downtown-dubai/burj-khalifa",
    "burj vista": "dubai/downtown-dubai/burj-vista",
    "the address downtown": "dubai/downtown-dubai/the-address-downtown",
    "boulevard point": "dubai/downtown-dubai/boulevard-point",
    "south ridge": "dubai/downtown-dubai/south-ridge",
    "old town": "dubai/downtown-dubai/old-town",

    # ---- Dubai Hills Estate ----
    "dubai hills estate": "dubai/dubai-hills-estate",
    "dubai hills": "dubai/dubai-hills-estate",
    "park heights": "dubai/dubai-hills-estate/park-heights",
    "park ridge": "dubai/dubai-hills-estate/park-ridge",
    "sidra": "dubai/dubai-hills-estate/sidra-villas",
    "maple": "dubai/dubai-hills-estate/maple-at-dubai-hills-estate",
    "golf place": "dubai/dubai-hills-estate/golf-place",
    "club villas": "dubai/dubai-hills-estate/club-villas-at-dubai-hills-estate",

    # ---- Dubai Creek Harbour ----
    "dubai creek harbour": "dubai/dubai-creek-harbour",
    "creek harbour": "dubai/dubai-creek-harbour",
    "creek beach": "dubai/dubai-creek-harbour/creek-beach",
    "harbour views": "dubai/dubai-creek-harbour/harbour-views",
    "creek rise": "dubai/dubai-creek-harbour/creek-rise",

    # ---- Palm Jumeirah ----
    "palm jumeirah": "dubai/palm-jumeirah",
    "the palm": "dubai/palm-jumeirah",
    "shoreline apartments": "dubai/palm-jumeirah/shoreline-apartments",
    "palm views": "dubai/palm-jumeirah/palm-views",
    "atlantis the royal residences": "dubai/palm-jumeirah/atlantis-the-royal-residences",
    "one at palm jumeirah": "dubai/palm-jumeirah/one-at-palm-jumeirah",
    "frond villas": "dubai/palm-jumeirah/frond-villas",

    # ---- Business Bay ----
    "business bay": "dubai/business-bay",
    "the executive towers": "dubai/business-bay/the-executive-towers",
    "bay square": "dubai/business-bay/bay-square",
    "paramount tower": "dubai/business-bay/paramount-tower-hotel-and-residences",

    # ---- Sobha Hartland / MBR City ----
    "sobha hartland": "dubai/sobha-hartland",
    "sobha hartland 2": "dubai/sobha-hartland-2",
    "mbr city": "dubai/mohammed-bin-rashid-city",
    "district one": "dubai/mohammed-bin-rashid-city/district-one",

    # ---- Jumeirah Lake Towers (JLT) ----
    "jumeirah lake towers": "dubai/jumeirah-lake-towers-jlt",
    "jlt": "dubai/jumeirah-lake-towers-jlt",
    "cluster a jlt": "dubai/jumeirah-lake-towers-jlt/cluster-a",
    "almas tower": "dubai/jumeirah-lake-towers-jlt/almas-tower",
    "indigo tower": "dubai/jumeirah-lake-towers-jlt/indigo-tower",

    # ---- Tilal Al Ghaf ----
    "tilal al ghaf": "dubai/tilal-al-ghaf",
    "harmona": "dubai/tilal-al-ghaf/harmona",
    "elan": "dubai/tilal-al-ghaf/elan",
    "alaya": "dubai/tilal-al-ghaf/alaya",

    # ---- Al Furjan ----
    "al furjan": "dubai/al-furjan",

    # ---- Town Square ----
    "town square": "dubai/town-square",
    "hayat townhouses": "dubai/town-square/hayat-townhouses",
    "zahra townhouses": "dubai/town-square/zahra-townhouses",
    "nshama town square": "dubai/town-square",

    # ---- Arabian Ranches ----
    "arabian ranches": "dubai/arabian-ranches",
    "arabian ranches 2": "dubai/arabian-ranches-2",
    "arabian ranches 3": "dubai/arabian-ranches-3",

    # ---- Emirates Living ----
    "the springs": "dubai/the-springs",
    "the meadows": "dubai/the-meadows",
    "the lakes": "dubai/the-lakes",
    "emirates hills": "dubai/emirates-hills",
    "the greens": "dubai/the-greens",
    "the views": "dubai/the-views",

    # ---- Al Barari / Mudon / Jumeirah Golf Estates ----
    "al barari": "dubai/al-barari",
    "mudon": "dubai/mudon",
    "jumeirah golf estates": "dubai/jumeirah-golf-estates",
    "jgd": "dubai/jumeirah-golf-estates",

    # ---- City Walk / Jumeirah / Al Wasl ----
    "city walk": "dubai/city-walk",
    "jumeirah 1": "dubai/jumeirah-1",
    "jumeirah 2": "dubai/jumeirah-2",
    "jumeirah 3": "dubai/jumeirah-3",
    "al wasl": "dubai/al-wasl",

    # ---- Deira / Bur Dubai ----
    "deira": "dubai/deira",
    "bur dubai": "dubai/bur-dubai",
    "al garhoud": "dubai/al-garhoud",
    "port saeed": "dubai/port-saeed",

    # ---- Dubai South / Expo ----
    "dubai south": "dubai/dubai-south",
    "expo city": "dubai/expo-city",

    # ---- Meydan ----
    "meydan": "dubai/meydan",
    "meydan one": "dubai/meydan/meydan-one",
    "district 7": "dubai/meydan/district-7",

    # ---- Al Jaddaf / Culture Village ----
    "al jaddaf": "dubai/al-jaddaf",
    "culture village": "dubai/al-jaddaf/dubai-culture-village",

    # ---- International City / Discovery Gardens ----
    "international city": "dubai/international-city",
    "discovery gardens": "dubai/discovery-gardens",

    # ---- Al Furjan-area & Discovery Gardens neighbors ----
    "the gardens": "dubai/the-gardens",
    "ibn battuta": "dubai/jebel-ali-1",

    # ---- Motor City / Sports City / Production City ----
    "motor city": "dubai/motor-city",
    "dubai sports city": "dubai/dubai-sports-city",
    "dubai production city": "dubai/international-media-production-zone-impz",
    "impz": "dubai/international-media-production-zone-impz",
    "dubai studio city": "dubai/dubai-studio-city",

    # ---- Al Sufouh / Media City / Internet City ----
    "al sufouh": "dubai/al-sufouh",
    "dubai media city": "dubai/dubai-media-city",
    "dubai internet city": "dubai/dubai-internet-city",
    "dubai knowledge park": "dubai/dubai-knowledge-park",

    # ---- Barsha / Tecom ----
    "al barsha": "dubai/al-barsha",
    "al barsha south": "dubai/al-barsha-south",
    "tecom": "dubai/al-thanyah-third",
    "greens and views": "dubai/the-views",

    # ---- Nad Al Sheba / Al Waha ----
    "nad al sheba": "dubai/nad-al-sheba",

    # ---- Living Legends / Falcon City ----
    "falcon city of wonders": "dubai/falcon-city-of-wonders",
    "living legends": "dubai/living-legends",

    # ---- The Villa / Serena / Wadi Al Safa ----
    "the villa": "dubai/the-villa",
    "serena": "dubai/serena",
    "villanova": "dubai/villanova",
    "amaranta": "dubai/villanova/amaranta",
    "fox hills": "dubai/damac-hills/fox-hills",

    # ---- Al Furjan neighboring: Discovery Gardens, Jebel Ali ----
    "jebel ali": "dubai/jebel-ali-1",
    "jebel ali village": "dubai/jebel-ali-village",
    "remraam": "dubai/remraam",

    # ---- Sobha (developer) ----
    "sobha one": "dubai/sobha-one",
    "sobha seahaven": "dubai/dubai-harbour/sobha-seahaven",
    "sobha creek vistas": "dubai/sobha-hartland/sobha-creek-vistas",

    # ---- Azizi (developer) ----
    "azizi riviera": "dubai/mohammed-bin-rashid-city/azizi-riviera",
    "azizi venice": "dubai/dubai-south/azizi-venice",

    # ---- Danube Properties (developer) ----
    "danube bayz": "dubai/business-bay/bayz-by-danube",
    "danube elitz": "dubai/jumeirah-village-circle/elitz-by-danube",
    "danube oceanz": "dubai/dubai-maritime-city/oceanz-by-danube",
    "danube skyz": "dubai/arjan/skyz-by-danube",
    "arjan": "dubai/arjan",

    # ---- Binghatti (developer) ----
    "binghatti canal": "dubai/business-bay/binghatti-canal",
    "binghatti stars": "dubai/al-jaddaf/binghatti-stars",
    "binghatti amber": "dubai/al-jaddaf/binghatti-amber",
    "binghatti jacob and co": "dubai/business-bay/binghatti-jacob-and-co",

    # ---- Ellington (developer) ----
    "ellington belgravia": "dubai/mudon/belgravia",
    "wilton terraces": "dubai/mohammed-bin-rashid-city/wilton-terraces",
    "ellington beach house": "dubai/palm-jumeirah/ellington-beach-house",

    # ---- Meraas (developer) ----
    "port de la mer": "dubai/jumeirah-1/port-de-la-mer",
    "bluewaters island": "dubai/bluewaters-island",
    "bluewaters": "dubai/bluewaters-island",
    "la mer": "dubai/jumeirah-1/la-mer",
    "pearl jumeirah": "dubai/pearl-jumeirah",
    "madinat jumeirah living": "dubai/umm-suqeim/madinat-jumeirah-living",
    "mjl": "dubai/umm-suqeim/madinat-jumeirah-living",
    "citywalk": "dubai/city-walk",

    # ---- Nakheel (developer, non-Palm) ----
    "jumeirah islands": "dubai/jumeirah-islands",
    "jumeirah park": "dubai/jumeirah-park",
    "the world islands": "dubai/the-world-islands",
    "deira islands": "dubai/deira-islands",
    "dragon city": "dubai/international-city/dragon-city",
    "warsan village": "dubai/warsan",
    "warsan": "dubai/warsan",

    # ---- Dubai Properties (developer) ----
    "villa lantana": "dubai/arabian-ranches/villa-lantana",
    "mudon views": "dubai/mudon/mudon-views",
    "manazel al khor": "dubai/al-khor",
    "1/JBR": "dubai/jumeirah-beach-residence-jbr/1-jbr",

    # ---- Deyaar / Select Group / Damac Properties (misc) ----
    "midtown": "dubai/dubailand/midtown",
    "dubailand": "dubai/dubailand",
    "the sustainable city": "dubai/the-sustainable-city",
    "wasl gate": "dubai/al-quoz/wasl-gate",
    "the oasis": "dubai/the-oasis",
    "the valley": "dubai/the-valley",
    "damac riverside": "dubai/damac-riverside",
    "damac islands": "dubai/damac-islands",

    # ---- Nshama (developer, beyond Town Square) ----
    "hayat boulevard": "dubai/town-square/hayat-boulevard",
    "syann park": "dubai/town-square/syann-park",

    # ---- Emaar (broader catalogue beyond Downtown/Hills) ----
    "emaar beachfront": "dubai/dubai-harbour/emaar-beachfront",
    "dubai harbour": "dubai/dubai-harbour",
    "rashid yachts and marina": "dubai/dubai-maritime-city/rashid-yachts-and-marina",
    "the valley by emaar": "dubai/the-valley",
    "arabian ranches iii": "dubai/arabian-ranches-3",
    "grand polo club and resort": "dubai/dubailand/grand-polo-club-and-resort",
    "the oasis by emaar": "dubai/the-oasis",

    # ---- Union Properties / Al Quoz / Motor City neighbors ----
    "green community": "dubai/green-community",
    "green community dip": "dubai/green-community/green-community-dip",
    "al quoz": "dubai/al-quoz",

    # ---- Wasl / Al Habtoor / misc luxury ----
    "habtoor city": "dubai/business-bay/habtoor-city",
    "al habtoor city": "dubai/business-bay/habtoor-city",
    "the lofts": "dubai/downtown-dubai/the-lofts",

    # ---- Layan / Reportage / Ghantoot / other smaller developers ----
    "reportage hills": "dubai/wadi-al-safa-5/reportage-hills",
    "ghantoot": "dubai/ghantoot",
    "layan community": "dubai/reem/layan-community",
    "reem": "dubai/reem",

    # ==========================================================
    # Hierarchical expansion: Master Project -> Sub-District/Cluster ->
    # Landmark Building, organized the way Dubai real estate actually is.
    # ==========================================================

    # ---- 1. Downtown Dubai & Sheikh Zayed Road Core ----
    "difc": "dubai/difc",
    "dubai international financial centre": "dubai/difc",
    "yansoon": "dubai/downtown-dubai/old-town/yansoon",
    "zaafaran": "dubai/downtown-dubai/old-town/zaafaran",
    "miska": "dubai/downtown-dubai/old-town/miska",
    "reehan": "dubai/downtown-dubai/old-town/reehan",
    "kamoon": "dubai/downtown-dubai/old-town/kamoon",
    "the residences downtown": "dubai/downtown-dubai/the-residences",
    "museum of the future": "dubai/trade-center/museum-of-the-future",
    "the index tower": "dubai/difc/the-index-tower",
    "jumeirah emirates towers": "dubai/trade-center/jumeirah-emirates-towers",
    "burj crown": "dubai/downtown-dubai/burj-crown",
    "il primo": "dubai/downtown-dubai/il-primo",
    "rp heights": "dubai/downtown-dubai/rp-heights",
    "opera grand": "dubai/downtown-dubai/opera-grand",
    "burj royale": "dubai/downtown-dubai/burj-royale",

    # ---- 2A. Dubai Marina & JBR ----
    "murjan": "dubai/jumeirah-beach-residence-jbr/murjan",
    "sadaf": "dubai/jumeirah-beach-residence-jbr/sadaf",
    "bahar": "dubai/jumeirah-beach-residence-jbr/bahar",
    "rimal": "dubai/jumeirah-beach-residence-jbr/rimal",
    "amwaj": "dubai/jumeirah-beach-residence-jbr/amwaj",
    "shams": "dubai/jumeirah-beach-residence-jbr/shams",
    "marina promenade": "dubai/dubai-marina/marina-promenade",
    "paloma": "dubai/dubai-marina/marina-promenade/paloma",
    "beauport": "dubai/dubai-marina/marina-promenade/beauport",
    "delphine": "dubai/dubai-marina/marina-promenade/delphine",
    "shemara": "dubai/dubai-marina/marina-promenade/shemara",
    "attessa": "dubai/dubai-marina/marina-promenade/attessa",
    "aurora": "dubai/dubai-marina/marina-promenade/aurora",
    "marina quays north": "dubai/dubai-marina/marina-quays/north",
    "marina quays east": "dubai/dubai-marina/marina-quays/east",
    "marina quays west": "dubai/dubai-marina/marina-quays/west",
    "marina 101": "dubai/dubai-marina/marina-101",
    "stella maris": "dubai/dubai-marina/stella-maris",
    "address beach resort": "dubai/emaar-beachfront/address-beach-resort",

    # ---- 2B. Jumeirah Lake Towers (JLT) — 26 lettered clusters + landmarks ----
    "lake plaza": "dubai/jumeirah-lake-towers-jlt/cluster-t/lake-plaza",
    "green lakes towers": "dubai/jumeirah-lake-towers-jlt/cluster-t/green-lakes-towers",
    "platinum tower": "dubai/jumeirah-lake-towers-jlt/cluster-i/platinum-tower",
    "gold tower": "dubai/jumeirah-lake-towers-jlt/cluster-i/gold-tower",
    "silver tower": "dubai/jumeirah-lake-towers-jlt/cluster-i/silver-tower",
    "goldcrest views": "dubai/jumeirah-lake-towers-jlt/cluster-j/goldcrest-views",
    "bonnington tower": "dubai/jumeirah-lake-towers-jlt/cluster-j/bonnington-tower",
    "uptown dubai": "dubai/jumeirah-lake-towers-jlt/uptown-dubai",
    "uptown tower": "dubai/jumeirah-lake-towers-jlt/uptown-dubai/uptown-tower",
    "saba towers": "dubai/jumeirah-lake-towers-jlt/saba-towers",
    "jumeirah business centre": "dubai/jumeirah-lake-towers-jlt/jumeirah-business-centre",
    "jbc towers": "dubai/jumeirah-lake-towers-jlt/jumeirah-business-centre",

    # ---- 3. Palm Jumeirah & Island Developments ----
    "palm jebel ali": "dubai/palm-jebel-ali",
    "dubai islands": "dubai/dubai-islands",
    "deira islands": "dubai/dubai-islands",
    "golden mile": "dubai/palm-jumeirah/golden-mile",
    "marina residences": "dubai/palm-jumeirah/marina-residences",
    "atlantis the palm": "dubai/palm-jumeirah/atlantis-the-palm",
    "atlantis the royal": "dubai/palm-jumeirah/atlantis-the-royal-residences",
    "the palm tower": "dubai/palm-jumeirah/the-palm-tower",
    "one za'abeel": "dubai/zabeel/one-zaabeel",
    "one zabeel": "dubai/zabeel/one-zaabeel",
    "the linx": "dubai/zabeel/one-zaabeel/the-linx",
    "five palm jumeirah": "dubai/palm-jumeirah/five-palm-jumeirah",

    # ---- 4. Inland Mega-Communities & Villa Suburbia ----
    "executive residences": "dubai/dubai-hills-estate/executive-residences",
    "hills park": "dubai/dubai-hills-estate/hills-park",
    "park field": "dubai/dubai-hills-estate/park-field",
    "lime gardens": "dubai/dubai-hills-estate/lime-gardens",
    "acacia": "dubai/dubai-hills-estate/acacia",
    "saheel": "dubai/arabian-ranches/saheel",
    "palmera": "dubai/arabian-ranches/palmera",
    "mirador": "dubai/arabian-ranches/mirador",
    "al reem arabian ranches": "dubai/arabian-ranches/al-reem",
    "joy": "dubai/arabian-ranches-2/joy",
    "spring arabian ranches": "dubai/arabian-ranches-2/spring",
    "bliss": "dubai/arabian-ranches-3/bliss",
    "golf horizon": "dubai/damac-hills/golf-horizon",
    "golf panorama": "dubai/damac-hills/golf-panorama",
    "venice townhouses": "dubai/damac-lagoons/venice",
    "bloom heights": "dubai/jumeirah-village-circle/bloom-heights",
    "signature livings": "dubai/jumeirah-village-circle/signature-livings",
    "diamond views": "dubai/jumeirah-village-circle/diamond-views",
    "sobha hartland greens": "dubai/sobha-hartland/greens",
    "sobha hartland waves": "dubai/sobha-hartland/waves",
    "waves grande": "dubai/sobha-hartland/waves-grande",
    "crest grande": "dubai/sobha-hartland/crest-grande",
    "hartland estates": "dubai/sobha-hartland/hartland-estates",

    # ---- 5. Heritage & Cultural Waterfronts ----
    "al fahidi historical district": "dubai/al-fahidi",
    "al fahidi": "dubai/al-fahidi",
    "gold souk extension": "dubai/deira/gold-souk-extension",
    "deira waterfront": "dubai/deira/deira-waterfront-development",
    "creek horizons": "dubai/dubai-creek-harbour/creek-horizons",
    "creek gate": "dubai/dubai-creek-harbour/creek-gate",
    "island district": "dubai/dubai-creek-harbour/island-district",
    "lotus dubai creek harbour": "dubai/dubai-creek-harbour/lotus",
    "creek palace": "dubai/dubai-creek-harbour/creek-palace",
    "mina rashid": "dubai/mina-rashid",
    "rashid yachts and marina": "dubai/mina-rashid/rashid-yachts-and-marina",
    "seascape": "dubai/mina-rashid/seascape",
    "sunridge": "dubai/mina-rashid/sunridge",
    "clearpoint": "dubai/mina-rashid/clearpoint",
}

# JLT's 26 lettered clusters (A-Z), each holding ~3 towers — added
# programmatically rather than by hand to stay readable.
for _cluster_letter in "abcdefghijklmnopqrstuvwxyz":
    LOCATION_DATABASE[f"jlt cluster {_cluster_letter}"] = f"dubai/jumeirah-lake-towers-jlt/cluster-{_cluster_letter}"

# Palm Jumeirah's private villa Fronds (A-N).
for _frond_letter in "abcdefghijklmn":
    LOCATION_DATABASE[f"frond {_frond_letter}"] = f"dubai/palm-jumeirah/frond-{_frond_letter}"

# Palm Jumeirah's Shoreline Apartments (Buildings 1-20).
for _n in range(1, 21):
    LOCATION_DATABASE[f"shoreline apartments {_n}"] = f"dubai/palm-jumeirah/shoreline-apartments/building-{_n}"

# Palm Jumeirah's Marina Residences (Buildings 1-6).
for _n in range(1, 7):
    LOCATION_DATABASE[f"marina residences {_n}"] = f"dubai/palm-jumeirah/marina-residences/building-{_n}"

# Palm Jumeirah's Golden Mile (Buildings 1-10).
for _n in range(1, 11):
    LOCATION_DATABASE[f"golden mile {_n}"] = f"dubai/palm-jumeirah/golden-mile/building-{_n}"

# JVC Districts 10-19.
for _n in range(10, 20):
    LOCATION_DATABASE[f"jvc district {_n}"] = f"dubai/jumeirah-village-circle/district-{_n}"

# ==========================================================
# 7. Exclusive Villa Enclaves & Golf Estates
# ==========================================================
_EMIRATES_LIVING_NAMED = {
    "montgomerie maison": "dubai/emirates-hills/montgomerie-maison",
    "al sidra": "dubai/the-greens/al-sidra",
    "al jasoor": "dubai/the-greens/al-jasoor",
    "al nakheel greens": "dubai/the-greens/al-nakheel",
    "al ghaf": "dubai/the-greens/al-ghaf",
    "al ghozlan": "dubai/the-greens/al-ghozlan",
    "al samar": "dubai/the-greens/al-samar",
    "al arta": "dubai/the-greens/al-arta",
    "al dhafrah greens": "dubai/the-greens/al-dhafrah",
    "fairways": "dubai/the-views/fairways",
    "golf towers": "dubai/the-views/golf-towers",
    "mosela": "dubai/the-views/mosela",
    "tanaro": "dubai/the-views/tanaro",
    "travo": "dubai/the-views/travo",
    "arno": "dubai/the-views/arno",
    "onaiza": "dubai/the-views/onaiza",
    "the links": "dubai/the-views/the-links",
}
LOCATION_DATABASE.update(_EMIRATES_LIVING_NAMED)
for _sector in "ehlprvw":
    LOCATION_DATABASE[f"emirates hills sector {_sector}"] = f"dubai/emirates-hills/sector-{_sector}"
for _n in range(1, 10):
    LOCATION_DATABASE[f"meadows {_n}"] = f"dubai/the-meadows/meadows-{_n}"
for _n in range(1, 16):
    LOCATION_DATABASE[f"springs {_n}"] = f"dubai/the-springs/springs-{_n}"
for _n in range(1, 5):
    LOCATION_DATABASE[f"deema {_n}"] = f"dubai/the-lakes/deema-{_n}"
for _n in range(1, 3):
    LOCATION_DATABASE[f"ghadeer {_n}"] = f"dubai/the-lakes/ghadeer-{_n}"
    LOCATION_DATABASE[f"zulal {_n}"] = f"dubai/the-lakes/zulal-{_n}"
for _n in range(1, 4):
    LOCATION_DATABASE[f"hattan {_n}"] = f"dubai/the-lakes/hattan-{_n}"

_JGE_ENCLAVES = [
    "whispering pines", "flame tree ridge", "fire side", "redwood avenue", "redwood park",
    "olive tree grove", "lime tree valley", "orange lake", "jumeirah luxury", "al andalus",
    "sanctuary falls", "sienna lakes", "wildflower", "hillside jumeirah golf estates", "valencia",
]
for _name in _JGE_ENCLAVES:
    LOCATION_DATABASE[_name] = f"dubai/jumeirah-golf-estates/{_name.replace(' ', '-')}"

for _n in range(1, 4):
    LOCATION_DATABASE[f"elan {_n}"] = f"dubai/tilal-al-ghaf/elan-{_n}"
    LOCATION_DATABASE[f"harmony {_n}"] = f"dubai/tilal-al-ghaf/harmony-{_n}"
LOCATION_DATABASE.update({
    "aura tilal al ghaf": "dubai/tilal-al-ghaf/aura",
    "aura gardens": "dubai/tilal-al-ghaf/aura-gardens",
    "alaya gardens": "dubai/tilal-al-ghaf/alaya-gardens",
    "elysian mansions": "dubai/tilal-al-ghaf/elysian-mansions",
    "waterfields": "dubai/tilal-al-ghaf/waterfields",
    "serenity mansions": "dubai/tilal-al-ghaf/serenity-mansions",
    "lanai islands shore estates": "dubai/tilal-al-ghaf/lanai-islands/shore-estates",
    "lanai islands edge estates": "dubai/tilal-al-ghaf/lanai-islands/edge-estates",
    "amara twin villas": "dubai/tilal-al-ghaf/amara",

    "the nest": "dubai/al-barari/the-nest",
    "ashjar": "dubai/al-barari/ashjar",
    "seventh heaven": "dubai/al-barari/seventh-heaven",
    "chorisia 1": "dubai/al-barari/chorisia-1",
    "chorisia 2": "dubai/al-barari/chorisia-2",
    "bromellia": "dubai/al-barari/bromellia",
    "camellia": "dubai/al-barari/camellia",
    "dahlia": "dubai/al-barari/dahlia",
    "acacia al barari": "dubai/al-barari/acacia",
    "jasmine al barari": "dubai/al-barari/jasmine",
    "al barari reserve": "dubai/al-barari/reserve",

    "jumeirah islands european cluster": "dubai/jumeirah-islands/european-cluster",
    "jumeirah islands islamic cluster": "dubai/jumeirah-islands/islamic-cluster",
    "jumeirah islands mediterranean cluster": "dubai/jumeirah-islands/mediterranean-cluster",
    "jumeirah islands oasis cluster": "dubai/jumeirah-islands/oasis-cluster",
    "jumeirah islands tropical cluster": "dubai/jumeirah-islands/tropical-cluster",
    "jumeirah islands contemporary cluster": "dubai/jumeirah-islands/contemporary-cluster",
    "jumeirah islands mansions": "dubai/jumeirah-islands/mansions-enclave",
    "jumeirah islands townhouses": "dubai/jumeirah-islands/townhouses",
    "jumeirah park regional": "dubai/jumeirah-park/regional",
    "jumeirah park legacy": "dubai/jumeirah-park/legacy",
    "jumeirah park heritage": "dubai/jumeirah-park/heritage",
    "jumeirah park nova villas": "dubai/jumeirah-park/nova-villas",
    "jumeirah park homes": "dubai/jumeirah-park/jumeirah-park-homes",
})

# ==========================================================
# 8. MBR City, Meydan & Dubailand Corridor
# ==========================================================
for _n in range(1, 17):
    LOCATION_DATABASE[f"residences at district one {_n}"] = f"dubai/mohammed-bin-rashid-city/district-one/residences-{_n}"
for _n in range(1, 7):
    LOCATION_DATABASE[f"hartland greens {_n}"] = f"dubai/sobha-hartland/hartland-greens-{_n}"
for _n in (320, 330, 340, 350):
    LOCATION_DATABASE[f"{_n} riverside crescent"] = f"dubai/sobha-hartland-2/{_n}-riverside-crescent"
for _n in range(1, 5):
    LOCATION_DATABASE[f"amaranta {_n}"] = f"dubai/villanova/amaranta-{_n}"
for _n in range(1, 7):
    LOCATION_DATABASE[f"la rosa {_n}"] = f"dubai/villanova/la-rosa-{_n}"
for _n in range(1, 4):
    LOCATION_DATABASE[f"arabella {_n}"] = f"dubai/mudon/arabella-{_n}"
LOCATION_DATABASE.update({
    "creek vistas tower a": "dubai/sobha-hartland/creek-vistas/tower-a",
    "creek vistas tower b": "dubai/sobha-hartland/creek-vistas/tower-b",
    "creek vistas reserve": "dubai/sobha-hartland/creek-vistas-reserve",
    "the crest sobha hartland": "dubai/sobha-hartland/the-crest",
    "sobha estates": "dubai/sobha-hartland/sobha-estates",
    "riviera azure": "dubai/mohammed-bin-rashid-city/azizi-riviera/riviera-azure",
    "riviera beachfront": "dubai/mohammed-bin-rashid-city/azizi-riviera/riviera-beachfront",
    "la quinta": "dubai/villanova/la-quinta",
    "rahat": "dubai/mudon/rahat",
    "naseem mudon": "dubai/mudon/naseem",
    "al salam mudon": "dubai/mudon/al-salam",
    "mudon al ranim": "dubai/mudon/al-ranim",
    "casa dora": "dubai/serena/casa-dora",
    "bella casa": "dubai/serena/bella-casa",
    "casa viva": "dubai/serena/casa-viva",
    "falcon city western residence": "dubai/falcon-city-of-wonders/western-residence",
    "falcon city eastern residence": "dubai/falcon-city-of-wonders/eastern-residence",
    "taj arabia": "dubai/falcon-city-of-wonders/taj-arabia",
    "hacienda the villa": "dubai/the-villa/hacienda",
    "ponderosa": "dubai/the-villa/ponderosa",
    "aldea": "dubai/the-villa/aldea",
    "centro the villa": "dubai/the-villa/centro",
})

# ==========================================================
# 9. Urban Regeneration & Central Districts
# ==========================================================
for _n in range(1, 22):
    LOCATION_DATABASE[f"city walk residences {_n}"] = f"dubai/city-walk/city-walk-residences-{_n}"
for _n in range(1, 6):
    LOCATION_DATABASE[f"la cote {_n}"] = f"dubai/jumeirah-1/port-de-la-mer/la-cote-{_n}"
for _n in range(1, 5):
    LOCATION_DATABASE[f"la rive {_n}"] = f"dubai/jumeirah-1/port-de-la-mer/la-rive-{_n}"
    LOCATION_DATABASE[f"le pont {_n}"] = f"dubai/jumeirah-1/port-de-la-mer/le-pont-{_n}"
for _n in range(1, 4):
    LOCATION_DATABASE[f"la voile {_n}"] = f"dubai/jumeirah-1/port-de-la-mer/la-voile-{_n}"
    LOCATION_DATABASE[f"la sirene {_n}"] = f"dubai/jumeirah-1/port-de-la-mer/la-sirene-{_n}"
for _n in range(1, 7):
    LOCATION_DATABASE[f"bulgari resort building {_n}"] = f"dubai/jumeirah-bay-island/bulgari-resort-and-residences/building-{_n}"
LOCATION_DATABASE.update({
    "central park laurel": "dubai/city-walk/central-park/laurel",
    "central park fern": "dubai/city-walk/central-park/fern",
    "central park myrtle": "dubai/city-walk/central-park/myrtle",
    "central park castleton": "dubai/city-walk/central-park/castleton",
    "central park celadon": "dubai/city-walk/central-park/celadon",
    "central park viridian": "dubai/city-walk/central-park/viridian",
    "central park erin": "dubai/city-walk/central-park/erin",
    "wasl1": "dubai/zabeel/wasl1",
    "park heights wasl1": "dubai/zabeel/wasl1/park-heights",
    "1 residences north tower": "dubai/zabeel/wasl1/1-residences-north-tower",
    "1 residences south tower": "dubai/zabeel/wasl1/1-residences-south-tower",
    "boxpark": "dubai/al-wasl/boxpark",
    "galleria residences": "dubai/al-wasl/galleria-residences",
    "al badia hillside village": "dubai/dubai-festival-city/al-badia-hillside-village",
    "al badia residences": "dubai/dubai-festival-city/al-badia-residences",
    "marsa plaza": "dubai/dubai-festival-city/marsa-plaza",
    "festival tower": "dubai/dubai-festival-city/festival-tower",
    "royal residence dfc": "dubai/dubai-festival-city/royal-residence",
    "sur la mer": "dubai/jumeirah-1/la-mer/sur-la-mer",
    "bulgari mansions": "dubai/jumeirah-bay-island/bulgari-mansions",
    "bulgari lighthouse": "dubai/jumeirah-bay-island/bulgari-lighthouse",
    "bulgari resort and residences": "dubai/jumeirah-bay-island/bulgari-resort-and-residences",
    "jumeirah bay island": "dubai/jumeirah-bay-island",
    "jardin astral": "dubai/al-satwa/jardin-astral",
    "villa amalfi": "dubai/jumeirah-bay-island/villa-amalfi",
})

# ==========================================================
# 10. Emerging Mega-Projects & Coastal Fronts
# ==========================================================
LOCATION_DATABASE.update({
    "ocean point": "dubai/mina-rashid/ocean-point",
    "marina views mina rashid": "dubai/mina-rashid/marina-views",
    "bayline": "dubai/mina-rashid/bayline",
    "avonlea": "dubai/mina-rashid/avonlea",
    "eden the valley": "dubai/the-valley/eden",
    "nara the valley": "dubai/the-valley/nara",
    "talia": "dubai/the-valley/talia",
    "orania": "dubai/the-valley/orania",
    "farm gardens": "dubai/the-valley/farm-gardens",
    "elora": "dubai/the-valley/elora",
    "rivana": "dubai/the-valley/rivana",
    "alana": "dubai/the-valley/alana",
    "neva": "dubai/the-valley/neva",
    "expo valley": "dubai/expo-city/expo-valley",
    "mangrove residences": "dubai/expo-city/mangrove-residences",
    "sky residences expo city": "dubai/expo-city/sky-residences",
    "yasmina villas": "dubai/expo-city/yasmina-villas",
    "golf views emaar south": "dubai/emaar-south/golf-views",
    "golf links emaar south": "dubai/emaar-south/golf-links",
    "fairway villas": "dubai/emaar-south/fairway-villas",
})
for _n in range(1, 4):
    LOCATION_DATABASE[f"urbana {_n}"] = f"dubai/emaar-south/urbana-{_n}"
for _n in range(1, 7):
    LOCATION_DATABASE[f"expo golf villas {_n}"] = f"dubai/emaar-south/expo-golf-villas-{_n}"

# ==========================================================
# 11. Mega-Villa Masters & Newly Launched Communities
# ==========================================================
for _letter in "abcdefghijklmnop":
    LOCATION_DATABASE[f"palm jebel ali frond {_letter}"] = f"dubai/palm-jebel-ali/frond-{_letter}"
for _n in range(1, 4):
    LOCATION_DATABASE[f"palmiera {_n}"] = f"dubai/the-oasis/palmiera-{_n}"
    LOCATION_DATABASE[f"serra {_n}"] = f"dubai/ghaf-woods/serra-{_n}"
LOCATION_DATABASE.update({
    "the crown palm jebel ali": "dubai/palm-jebel-ali/the-crown",
    "crescent enclaves": "dubai/palm-jebel-ali/crescent-enclaves",
    "mirage at the oasis": "dubai/the-oasis/mirage",
    "strand the oasis": "dubai/the-oasis/strand",
    "ghaf woods": "dubai/ghaf-woods",
    "evergreen enclaves": "dubai/ghaf-woods/evergreen-enclaves",
    "forest residences": "dubai/ghaf-woods/forest-residences",
    "the acres": "dubai/the-acres",
    "the acres phase 1": "dubai/the-acres/phase-1",
    "the acres phase 2": "dubai/the-acres/phase-2",
    "the acres gardens": "dubai/the-acres/the-acres-gardens",
    "maldives": "dubai/damac-islands/maldives",
    "bora bora": "dubai/damac-islands/bora-bora",
    "seychelles": "dubai/damac-islands/seychelles",
    "hawaii": "dubai/damac-islands/hawaii",
    "bali": "dubai/damac-islands/bali",
    "fiji": "dubai/damac-islands/fiji",
})

# ==========================================================
# 12. Waterfront Regeneration & Port Districts
# ==========================================================
for _letter in "abcde":
    LOCATION_DATABASE[f"dubai islands island {_letter}"] = f"dubai/dubai-islands/island-{_letter}"
LOCATION_DATABASE.update({
    "flora bay by octa": "dubai/dubai-islands/island-a/flora-bay-by-octa",
    "sea cliff by imtiaz": "dubai/dubai-islands/sea-cliff-by-imtiaz",
    "mackerel tower": "dubai/dubai-islands/mackerel-tower",
    "ocean pearl by samana": "dubai/dubai-islands/ocean-pearl-by-samana",
    "rixos dubai islands": "dubai/dubai-islands/rixos-hotel-and-residences",
    "centara mirage beach resort": "dubai/dubai-islands/centara-mirage-beach-resort",
    "dubai maritime city": "dubai/dubai-maritime-city",
    "nautica one": "dubai/dubai-maritime-city/nautica-one",
    "nautica two": "dubai/dubai-maritime-city/nautica-two",
    "anwa by omniyat": "dubai/dubai-maritime-city/anwa",
    "anwa aria": "dubai/dubai-maritime-city/anwa-aria",
    "mar casa by deyaar": "dubai/dubai-maritime-city/mar-casa",
    "harbour lights by damac": "dubai/dubai-maritime-city/harbour-lights",
    "ocean house dmc": "dubai/dubai-maritime-city/ocean-house",
})

# ==========================================================
# 13. Meydan Horizon & MBR City Extensions
# ==========================================================
for _n in range(1, 5):
    LOCATION_DATABASE[f"nad al sheba {_n}"] = f"dubai/nad-al-sheba/nad-al-sheba-{_n}"
for _n in range(1, 7):
    LOCATION_DATABASE[f"nad al sheba gardens phase {_n}"] = f"dubai/nad-al-sheba/nad-al-sheba-gardens/phase-{_n}"
LOCATION_DATABASE.update({
    "meydan horizon": "dubai/meydan/meydan-horizon",
    "canal promenade": "dubai/meydan/meydan-horizon/canal-promenade",
    "lagoon front meydan": "dubai/meydan/meydan-horizon/lagoon-front",
    "the winslow by igo": "dubai/meydan/the-winslow",
    "meydan heights": "dubai/meydan/meydan-heights",
    "keturah reserve": "dubai/meydan/keturah-reserve",
    "queens garden nad al sheba": "dubai/nad-al-sheba/queens-garden",
})

# ==========================================================
# 14. Emerging Hyper-Towers & Branded High-Rises
# ==========================================================
LOCATION_DATABASE.update({
    "burj azizi": "dubai/sheikh-zayed-road/burj-azizi",
    "burj binghatti jacob and co residences": "dubai/business-bay/burj-binghatti-jacob-and-co",
    "ciel tower": "dubai/dubai-marina/ciel-tower",
    "franck muller aeternitas": "dubai/dubai-marina/franck-muller-aeternitas",
    "mercedes-benz places": "dubai/downtown-dubai/mercedes-benz-places",
    "bugatti residences": "dubai/business-bay/bugatti-residences",
    "aire dubai": "dubai/al-wasl/aire",
    "one zaabeel tower a": "dubai/zabeel/one-zaabeel/tower-a",
    "one zaabeel tower b": "dubai/zabeel/one-zaabeel/tower-b",
})

# ==========================================================
# 15. Specialized Innovation & Creative Hubs
# ==========================================================
for _n in range(1, 8):
    LOCATION_DATABASE[f"afnan {_n}"] = f"dubai/international-media-production-zone-impz/midtown/afnan-{_n}"
for _n in range(1, 7):
    LOCATION_DATABASE[f"dania {_n}"] = f"dubai/international-media-production-zone-impz/midtown/dania-{_n}"
for _n in range(1, 5):
    LOCATION_DATABASE[f"mesk {_n}"] = f"dubai/international-media-production-zone-impz/midtown/mesk-{_n}"
    LOCATION_DATABASE[f"noor {_n}"] = f"dubai/international-media-production-zone-impz/midtown/noor-{_n}"
    LOCATION_DATABASE[f"centrium tower {_n}"] = f"dubai/international-media-production-zone-impz/centrium-towers/tower-{_n}"
    LOCATION_DATABASE[f"opalz by danube {_n}"] = f"dubai/dubai-science-park/opalz-by-danube-{_n}"
for _n in range(1, 12):
    LOCATION_DATABASE[f"d3 creative block {_n}"] = f"dubai/dubai-design-district-d3/creative-block-{_n}"
LOCATION_DATABASE.update({
    "crescent towers": "dubai/international-media-production-zone-impz/crescent-towers",
    "lago vista": "dubai/international-media-production-zone-impz/lago-vista",
    "oakley square residences": "dubai/international-media-production-zone-impz/oakley-square-residences",
    "lago residences": "dubai/international-media-production-zone-impz/lago-residences",
    "mont rose tower a": "dubai/dubai-science-park/mont-rose/tower-a",
    "mont rose tower b": "dubai/dubai-science-park/mont-rose/tower-b",
    "mont rose executive": "dubai/dubai-science-park/mont-rose-executive",
    "bella rose": "dubai/dubai-science-park/bella-rose",
    "sayacorp tower": "dubai/dubai-science-park/sayacorp-tower",
    "villa lantana dsp": "dubai/barsha-south/villa-lantana",
    "atelis at d3": "dubai/dubai-design-district-d3/atelis",
    "the edit at d3": "dubai/dubai-design-district-d3/the-edit",
})

# ==========================================================
# 16. Developer-Specific Mega-Portfolios & Master Enclaves
# ==========================================================
for _n in range(1, 4):
    LOCATION_DATABASE[f"elitz {_n}"] = f"dubai/jumeirah-village-circle/elitz-{_n}"
for _n in range(1, 3):
    LOCATION_DATABASE[f"viewz {_n}"] = f"dubai/jumeirah-lake-towers-jlt/viewz-{_n}"
for _n in range(1, 4):
    LOCATION_DATABASE[f"oceanz {_n}"] = f"dubai/dubai-maritime-city/oceanz-{_n}"
for _n in range(1, 3):
    LOCATION_DATABASE[f"the nook {_n}"] = f"dubai/jebel-ali/wasl-gate/the-nook-{_n}"
for _letter in "abcde":
    LOCATION_DATABASE[f"south garden {_letter}"] = f"dubai/jebel-ali/wasl-gate/south-garden-{_letter}"
for _letter in "abcd":
    LOCATION_DATABASE[f"park gate residences tower {_letter}"] = f"dubai/zabeel/wasl1/park-gate-residences/tower-{_letter}"
LOCATION_DATABASE.update({
    "wasl gate": "dubai/jebel-ali/wasl-gate",
    "bayz 101": "dubai/business-bay/bayz-101",
    "fashionz by danube": "dubai/jumeirah-lake-towers-jlt/fashionz-by-danube",
    "sportz by danube": "dubai/dubai-sports-city/sportz-by-danube",
    "gemz by danube": "dubai/al-furjan/gemz-by-danube",
    "gardenia townhomes": "dubai/jebel-ali/wasl-gate/gardenia-townhomes",
    "hillside residences wasl": "dubai/jebel-ali/wasl-gate/hillside-residences",
    "sola residences": "dubai/jebel-ali/wasl-gate/sola-residences",
    "hammock park": "dubai/jebel-ali/wasl-gate/hammock-park",
    "taiyo residences": "dubai/jebel-ali/wasl-gate/taiyo-residences",
    "wasl tower": "dubai/zabeel/wasl-tower",
    "binghatti trillionaire": "dubai/business-bay/binghatti-trillionaire",
    "binghatti crest": "dubai/business-bay/binghatti-crest",
    "binghatti rose": "dubai/jumeirah-village-circle/binghatti-rose",
    "binghatti mirage": "dubai/jumeirah-village-triangle/binghatti-mirage",
    "binghatti corner": "dubai/jumeirah-village-circle/binghatti-corner",
    "binghatti phantom": "dubai/jumeirah-village-triangle/binghatti-phantom",
    "binghatti lavender": "dubai/jumeirah-village-circle/binghatti-lavender",
    "binghatti circle": "dubai/jumeirah-village-circle/binghatti-circle",
    "binghatti avenue": "dubai/al-jaddaf/binghatti-avenue",
    "binghatti gateway": "dubai/al-jaddaf/binghatti-gateway",
    "binghatti wraith": "dubai/al-jaddaf/binghatti-wraith",
})

# ==========================================================
# 17. Al Khail Corridor & Mirdif Expansions
# ==========================================================
for _n in range(1, 6):
    LOCATION_DATABASE[f"al warqaa {_n}"] = f"dubai/al-warqa/al-warqaa-{_n}"
LOCATION_DATABASE.update({
    "al khail heights": "dubai/al-khail-heights",
    "mirdif tulips": "dubai/mirdif/mirdif-tulips",
    "shorooq mirdif": "dubai/mirdif/shorooq",
    "ghoroob mirdif": "dubai/mirdif/ghoroob",
    "uptim mirdif": "dubai/mirdif/uptim",
    "mushrif village": "dubai/mirdif/mushrif-village",
})

# ==========================================================
# 18-28. DAMAC/Ellington enclaves, Samana/Azizi portfolios, DLRC/City of
# Arabia, Sobha extensions, luxury branded towers, healthcare/industrial
# clusters, mega-townships, and mid-market corridors.
# ==========================================================
for _n in range(1, 12):
    LOCATION_DATABASE[f"nad al sheba gardens phase {_n}"] = f"dubai/nad-al-sheba/nad-al-sheba-gardens/phase-{_n}"
for _n in range(1, 16):
    LOCATION_DATABASE[f"azizi venice lagoon cluster {_n}"] = f"dubai/dubai-south/azizi-venice/lagoon-cluster-{_n}"
for _letter in "abcdef":
    LOCATION_DATABASE[f"skycourts tower {_letter}"] = f"dubai/dubailand-residence-complex/skycourts-towers/tower-{_letter}"
for _n in range(1, 5):
    LOCATION_DATABASE[f"silicon gates {_n}"] = f"dubai/dubai-silicon-oasis/silicon-gates-{_n}"
for _n in range(1, 12):
    LOCATION_DATABASE[f"automotive residences tower {_n}"] = f"dubai/nad-al-sheba/mercedes-benz-places-binghatti-city/automotive-residences-{_n}"

LOCATION_DATABASE.update({
    "damac riverside": "dubai/damac-riverside",
    "riverside ivy": "dubai/damac-riverside/ivy",
    "riverside sage": "dubai/damac-riverside/sage",
    "riverside jasmine": "dubai/damac-riverside/jasmine",
    "riverside olive": "dubai/damac-riverside/olive",
    "riverside willow": "dubai/damac-riverside/willow",
    "the highgrove": "dubai/business-bay/the-highgrove",
    "the crestmark": "dubai/business-bay/the-crestmark",
    "bellevue walk": "dubai/business-bay/bellevue-walk",
    "arbor view": "dubai/jumeirah-village-triangle/arbor-view",
    "mercer house": "dubai/jumeirah-village-triangle/mercer-house",
    "wilton park residences": "dubai/jumeirah-village-circle/wilton-park-residences",
    "hamilton house": "dubai/jumeirah-village-circle/hamilton-house",
    "upper house jlt": "dubai/jumeirah-lake-towers-jlt/upper-house",
    "belgravia heights 1": "dubai/mudon/belgravia-heights-1",
    "belgravia heights 2": "dubai/mudon/belgravia-heights-2",

    "samana boulevard heights": "dubai/dubailand-residence-complex/samana-boulevard-heights",
    "samana ivy gardens 1": "dubai/dubailand-residence-complex/samana-ivy-gardens-1",
    "samana ivy gardens 2": "dubai/dubailand-residence-complex/samana-ivy-gardens-2",
    "samana waves": "dubai/dubailand-residence-complex/samana-waves",
    "samana imperial gardens": "dubai/arjan/samana-imperial-gardens",
    "samana barari avenue": "dubai/majan/samana-barari-avenue",
    "samana golf avenue": "dubai/majan/samana-golf-avenue",
    "samana park views": "dubai/arjan/samana-park-views",
    "samana hills south": "dubai/majan/samana-hills-south",
    "samana ocean bay": "dubai/dubai-islands/samana-ocean-bay",
    "samana portofino": "dubai/international-media-production-zone-impz/samana-portofino",
    "samana manhattan": "dubai/jumeirah-village-circle/samana-manhattan",
    "samana miami": "dubai/jumeirah-village-circle/samana-miami",
    "samana skyros": "dubai/jumeirah-village-triangle/samana-skyros",
    "azizi plaza": "dubai/al-furjan/azizi-plaza",
    "azizi star": "dubai/al-furjan/azizi-star",
    "azizi farishta": "dubai/al-furjan/azizi-farishta",
    "azizi shaista": "dubai/al-furjan/azizi-shaista",
    "azizi montrell": "dubai/al-furjan/azizi-montrell",
    "azizi mina": "dubai/palm-jumeirah/azizi-mina",

    "nuve by zoya": "dubai/dubailand-residence-complex/nuve-by-zoya",
    "ag central": "dubai/dubailand-residence-complex/ag-central",
    "desert sun": "dubai/dubailand-residence-complex/desert-sun",
    "silicon oasis edges": "dubai/dubai-silicon-oasis/edges",
    "arancia yards": "dubai/city-of-arabia/arancia-yards",
    "wadi walk": "dubai/city-of-arabia/wadi-walk",
    "metro tower city of arabia": "dubai/city-of-arabia/metro-tower",
    "sakura gardens by hre": "dubai/falcon-city-of-wonders/sakura-gardens",
    "pyramids park": "dubai/falcon-city-of-wonders/pyramids-park",

    "sobha sanctuary": "dubai/wadi-al-safa-4/sobha-sanctuary",
    "the willows at sobha sanctuary": "dubai/wadi-al-safa-4/sobha-sanctuary/the-willows",
    "sobha central": "dubai/sheikh-zayed-road/sobha-central",
    "the mirage at sobha central": "dubai/sheikh-zayed-road/sobha-central/the-mirage",
    "skyvue stellar": "dubai/sobha-hartland-2/skyvue-stellar",
    "skyvue horizon": "dubai/sheikh-zayed-road/sobha-central/skyvue-horizon",
    "the pinnacle at sobha central": "dubai/sheikh-zayed-road/sobha-central/the-pinnacle",
    "sobha elwood": "dubai/wadi-al-safa-4/sobha-elwood",
    "sobha reserve": "dubai/dubailand/sobha-reserve",
    "sobha solis": "dubai/motor-city/sobha-solis",
    "sobha orbis": "dubai/motor-city/sobha-orbis",
    "alton by nshama": "dubai/town-square/alton",
    "rosewell by nshama": "dubai/town-square/rosewell",
    "mahra town square": "dubai/town-square/mahra",
    "symphony town square": "dubai/town-square/symphony",
    "regora": "dubai/town-square/regora",
    "orchid town square": "dubai/town-square/orchid",

    "safa one tower a": "dubai/al-safa/safa-one/tower-a",
    "safa one tower b": "dubai/al-safa/safa-one/tower-b",
    "safa two": "dubai/al-safa/safa-two",
    "safa gate": "dubai/al-safa/safa-gate",
    "couture by cavalli": "dubai/business-bay/couture-by-cavalli",
    "canal crown": "dubai/business-bay/canal-crown",
    "volante tower": "dubai/business-bay/volante-tower",
    "the sterling": "dubai/business-bay/the-sterling",
    "marquise square tower": "dubai/business-bay/marquise-square-tower",
    "damac bay 1": "dubai/dubai-harbour/damac-bay-1",
    "damac bay 2": "dubai/dubai-harbour/damac-bay-2",
    "sobha seahaven": "dubai/dubai-harbour/sobha-seahaven",
    "chelsea residences": "dubai/business-bay/chelsea-residences",
    "como residences": "dubai/palm-jumeirah/como-residences",
    "palm beach towers": "dubai/palm-jumeirah/palm-beach-towers",
    "lumiere residences": "dubai/business-bay/lumiere-residences",
    "liora residences": "dubai/dubai-islands/liora-residences",
    "beachgate by address": "dubai/emaar-beachfront/beachgate-by-address",
    "bayview by address": "dubai/emaar-beachfront/bayview-by-address",
    "south beach emaar beachfront": "dubai/emaar-beachfront/south-beach",
    "beach mansion": "dubai/emaar-beachfront/beach-mansion",
    "sunrise bay": "dubai/emaar-beachfront/sunrise-bay",
    "marina vista": "dubai/emaar-beachfront/marina-vista",
    "grand bleu tower": "dubai/emaar-beachfront/grand-bleu-tower",
    "bay grove residences": "dubai/dubai-islands/bay-grove-residences",
    "bay villas dubai islands": "dubai/dubai-islands/bay-villas",
    "rixos beach residences": "dubai/dubai-islands/rixos-beach-residences",

    "cedre villas": "dubai/dubai-silicon-oasis/cedre-villas",
    "semmer villas": "dubai/dubai-silicon-oasis/semmer-villas",
    "binghatti crystals": "dubai/dubai-silicon-oasis/binghatti-crystals",
    "binghatti jewels": "dubai/dubai-silicon-oasis/binghatti-jewels",
    "binghatti horizons": "dubai/dubai-silicon-oasis/binghatti-horizons",
    "greenz by danube": "dubai/academic-city/greenz-by-danube",

    "haven by aldar": "dubai/dubailand/haven-by-aldar",
    "athlon by aldar": "dubai/dubailand/athlon-by-aldar",
    "verdes by haven": "dubai/dubailand/haven-by-aldar/verdes",
    "peninsula": "dubai/business-bay/peninsula",
    "peninsula five": "dubai/business-bay/peninsula/peninsula-five",
    "six senses residences": "dubai/palm-jumeirah/six-senses-residences",
    "artistry one residences": "dubai/dubai-design-district-d3/artistry-one-residences",
    "eden house the canal": "dubai/al-safa/eden-house-the-canal",
    "eden house the park": "dubai/al-safa/eden-house-the-park",

    "samana south haven": "dubai/dubai-south/samana-south-haven",
    "cresswell plaza": "dubai/dubai-south/cresswell-plaza",
    "views vii by golden woods": "dubai/dubai-south/views-vii",
    "orchid residence 1": "dubai/dubai-south/orchid-residence-1",
    "jebel ali village": "dubai/jebel-ali-village",
    "raw district 1": "dubai/downtown-jebel-ali/raw-district-1",
    "raw district 2": "dubai/downtown-jebel-ali/raw-district-2",
    "azizi rose": "dubai/downtown-jebel-ali/azizi-rose",

    "the heights country club": "dubai/dubailand/the-heights-country-club",
    "the heights townhouses": "dubai/dubailand/the-heights-country-club/townhouses",
    "grand polo club and resort": "dubai/dubailand/grand-polo-club-and-resort",
    "polo estate villas": "dubai/dubailand/grand-polo-club-and-resort/polo-estate",
    "skyhills residences": "dubai/dubai-science-park/skyhills-residences",
    "skyhills astra": "dubai/dubai-science-park/skyhills-astra",
    "celeste tower": "dubai/dubai-science-park/celeste-tower",
    "amazonia by palladium": "dubai/al-jaddaf/amazonia",
    "keturah resort residences": "dubai/al-jaddaf/keturah-resort-residences",
    "al habtoor tower": "dubai/business-bay/al-habtoor-tower",

    "al razi building": "dubai/dubai-healthcare-city/al-razi-building",
    "ibn sina building": "dubai/dubai-healthcare-city/ibn-sina-building",
    "creek heights residences": "dubai/dubai-healthcare-city/creek-heights-residences",
    "azizi aliyah": "dubai/dubai-healthcare-city/azizi-aliyah",
    "azizi farhad": "dubai/dubai-healthcare-city/azizi-farhad",
    "dubai international academic city": "dubai/dubai-international-academic-city",
    "dubai south logistics district": "dubai/dubai-south/logistics-district",
    "national industries park": "dubai/national-industries-park",
})

BEDROOM_LABELS: Dict[str, str] = {
    "a": "All Bedrooms", "0": "Studio", "1": "1 Bedroom", "2": "2 Bedrooms",
    "3": "3 Bedrooms", "4": "4 Bedrooms", "5": "5+ Bedrooms",
}


def format_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text


# Bayut's homepage location search box, and its autocomplete dropdown, are
# what actually knows about every project/building/cluster on the site —
# a hardcoded dictionary never can. The first entries below are verified
# against Bayut's real markup (inspected directly): the classic "filters"
# search form has
#   <div aria-label="Location filter" name="location">
#     ...
#       <div aria-label="Location filter">
#         <ul></ul>   <-- populated with <li> suggestions after typing
#         <input placeholder="Enter location" .../>
#       </div>
# CSS module class names on that markup are hashed per-deploy (e.g.
# "_2fb11f82") so they're deliberately not used here — placeholder/
# aria-label/structural position are the stable anchors. Remaining
# entries are best-effort fallbacks tried in order until one works.
LOCATION_SEARCH_INPUT_SELECTORS = [
    "css:input[placeholder='Enter location']",
    "css:[aria-label='Location filter'] input",
    "css:input[placeholder*='location' i]",
    "css:input[placeholder*='area' i]",
    "css:input[placeholder*='project' i]",
    "css:input[placeholder*='search' i]",
    "css:input[name*='location' i]",
    "css:input[aria-label*='location' i]",
    "css:[data-testid*='location'] input",
    "css:[class*='LocationSearch'] input",
    "css:[class*='location-search'] input",
]

# The dropdown renders as <li> items inside the same "Location filter"
# container the input lives in (confirmed live: typing populates the
# sibling <ul>), so anchoring on that container beats guessing at hashed
# suggestion/dropdown class names.
LOCATION_SUGGESTION_SELECTORS = [
    "css:[aria-label='Location filter'] ul li",
    "css:[aria-label='Location filter'] li",
    "css:[role='listbox'] [role='option']",
    "css:[class*='suggestion'] a",
    "css:[class*='Suggestion'] a",
    "css:[class*='autocomplete'] li a",
    "css:[class*='dropdown'] a[href*='/dubai/']",
    "css:ul li a[href*='/dubai/']",
]

# After picking a suggestion, the classic filter form doesn't navigate on
# its own (confirmed live: there's a distinct "Search" button next to the
# location box) — it just fills the field. This has to be clicked to
# actually land on the results page.
SEARCH_SUBMIT_SELECTORS = [
    "xpath://button[contains(., 'Search')]",
    "text:Search",
]


def resolve_location_via_site_search(page: "ChromiumPage", user_input: str) -> Optional[str]:
    """Type the free-text project/building/area name into Bayut's own
    search box and follow its first autocomplete suggestion, so lookups
    aren't limited to our local shortcut dictionary. Returns the resolved
    'dubai/...' path, or None if the search UI couldn't be driven."""
    try:
        page.get("https://www.bayut.com/")
        time.sleep(1.5)
        handle_captcha(page)

        search_input = None
        for selector in LOCATION_SEARCH_INPUT_SELECTORS:
            search_input = page.ele(selector, timeout=1)
            if search_input:
                break
        if not search_input:
            logger.debug("Could not find Bayut's location search box.")
            return None

        search_input.click()
        search_input.input(user_input)
        time.sleep(1.8)  # let autocomplete suggestions load

        suggestion = None
        for selector in LOCATION_SUGGESTION_SELECTORS:
            suggestion = page.ele(selector, timeout=1)
            if suggestion:
                break
        if not suggestion:
            logger.debug("No autocomplete suggestion found for '%s'.", user_input)
            return None

        # Suggestion rows aren't always <a href>: on the classic filter
        # form they're plain <li> text that just fills the field, so an
        # explicit "Search" click is needed afterwards to navigate.
        href = suggestion.attr("href") or ""
        suggestion.click()
        time.sleep(1.2)

        if not href and page.url.rstrip("/") == "https://www.bayut.com":
            for selector in SEARCH_SUBMIT_SELECTORS:
                submit_btn = page.ele(selector, timeout=1)
                if submit_btn:
                    submit_btn.click()
                    time.sleep(1.8)
                    break

        href = href or page.url

        match = re.search(r"bayut\.com/(?:(?:for-sale|to-rent)/(?:[\w-]+-property/)?)?(dubai/[\w/-]+?)/?(?:$|\?)", href)
        if match:
            return match.group(1)
        return None
    except Exception as exc:
        logger.debug("Site-search location resolution failed for '%s': %s", user_input, exc)
        return None


def resolve_location(user_input: str, page: Optional["ChromiumPage"] = None) -> Tuple[str, str]:
    """Resolution order, most-trustworthy first:
      1. Bayut's own live search (authoritative — it's their real data,
         works for ANY project/building/cluster, not just ones we've
         hand-entered). Tried first whenever a browser page is available.
      2. Local shortcut database — exact match, then fuzzy-typo match.
         Used when there's no page (e.g. unit tests) or live search fails.
      3. A raw slugified guess as the last resort.
    Hardcoded per-building slug guesses proved unreliable in practice
    (DAMAC Tower 108, Westwood Grande, Costa Brava all pointed at dead
    URLs Bayut silently redirected off of) — live search avoids that
    entirely since it's driven by Bayut's own resolved data, not a guess.
    """
    clean_input = user_input.lower().strip()

    if page is not None:
        live_path = resolve_location_via_site_search(page, user_input)
        if live_path:
            cprint(f"🔎 Found '{user_input}' via Bayut's own search ---> {live_path}")
            return live_path, user_input.title()
        cprint(f"⚠️  Bayut's own search couldn't resolve '{user_input}' — trying the local shortcut list.")

    if clean_input in LOCATION_DATABASE:
        return LOCATION_DATABASE[clean_input], clean_input.title()
    keys = list(LOCATION_DATABASE.keys())
    # cutoff=0.60 only auto-corrects genuine typos (e.g. "dama hils" ->
    # "damac hills"); anything looser starts matching unrelated projects.
    matches = difflib.get_close_matches(clean_input, keys, n=1, cutoff=0.60)
    if matches:
        best_match = matches[0]
        cprint(f"💡 Auto-corrected spelling '{user_input}' ---> Matched to: '{best_match.title()}'")
        return LOCATION_DATABASE[best_match], best_match.title()

    cprint(f"⚠️  Could not confidently resolve '{user_input}' — using a guessed URL.")
    cprint("    Results may be off-target; check the 'Location Match' column afterwards.")
    formatted_slug = format_slug(user_input)
    if formatted_slug and formatted_slug != "uae":
        return f"dubai/{formatted_slug}", user_input.title()
    return "dubai", "Dubai"


GENERIC_LOCATION_WORDS = {
    "dubai", "uae", "villa", "villas", "townhouse", "townhouses", "apartment",
    "apartments", "for", "sale", "rent", "the", "by", "at", "and", "property",
}


def location_matches(extracted: str, expected: str) -> bool:
    """Best-effort sanity check: does the location Bayut actually returned
    share any meaningful word with what the user searched for? Used to flag
    (not silently trust) listings that come back from a mismatched/guessed
    URL slug — see the 'Location Match' column."""
    def tokens(s: str):
        return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in GENERIC_LOCATION_WORDS and len(w) > 2}

    exp_tokens = tokens(expected)
    ext_tokens = tokens(extracted)
    if not exp_tokens or not ext_tokens:
        return True  # not enough signal either way — don't flag a false positive
    return bool(exp_tokens & ext_tokens)


def build_bayut_url(purpose_choice: str, bed_choice: str, location_path: str) -> str:
    purpose_slug = "to-rent" if purpose_choice == "2" else "for-sale"
    # NOTE: the choice value IS the bedroom count (0=Studio ... 5=5+ Beds).
    # "All Bedrooms" is its own sentinel ("a"), not a numeric slot, so there
    # is no off-by-one shift between what the user types and what they get.
    bed_slugs = {
        "0": "studio-property", "1": "1-bedroom-property", "2": "2-bedroom-property",
        "3": "3-bedroom-property", "4": "4-bedroom-property", "5": "5-bedroom-property",
    }
    bed_slug = bed_slugs.get(bed_choice, "property")
    return f"https://www.bayut.com/{purpose_slug}/{bed_slug}/{location_path}/"


@dataclass
class ScrapeConfig:
    purpose_str: str
    location: str
    bedrooms_label: str
    max_listings: Optional[int]
    target_url: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bayut Scraper Engine")
    parser.add_argument("--purpose", choices=["1", "2"], help="1=Buy, 2=Rent")
    parser.add_argument("--location", help="Project / community / area name")
    parser.add_argument("--bedrooms", choices=["a"] + [str(i) for i in range(6)],
                         help="a=All, 0=Studio, 1..4=that many beds, 5=5+ Beds")
    parser.add_argument("--max-listings", type=int, help="Cap on number of listings")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--out", help="Output .xlsx path (default: Desktop, auto-named)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug-level logging")
    parser.add_argument("--log-file", help="Also write logs to this file")
    parser.add_argument(
        "--no-trakheesi", dest="verify_trakheesi", action="store_false",
        help="Skip following the Trakheesi/DLD permit QR link for verified agent details (faster)",
    )
    parser.set_defaults(verify_trakheesi=True)
    return parser.parse_args()


def get_user_inputs(args: argparse.Namespace, page: Optional[ChromiumPage] = None) -> ScrapeConfig:
    print_logo()
    cprint("=" * 70)
    cprint("     SMART BAYUT SCRAPER ENGINE (STRUCTURED-DATA EDITION)     ")
    cprint("=" * 70)

    purpose = args.purpose
    if not purpose:
        cprint("\n1. Purpose:")
        cprint("   1. Buy (For Sale)")
        cprint("   2. Rent (To Rent)")
        purpose = input(f"{GREEN}Choice (1 or 2, default 1): {RESET}").strip() or "1"

    location_raw = args.location
    if not location_raw:
        location_raw = input(f"\n{GREEN}2. Project, Villa Cluster, Building, or Area: {RESET}").strip()
    if not location_raw:
        location_raw = "Dubai"

    loc_path, resolved_name = resolve_location(location_raw, page=page)

    bedrooms = args.bedrooms
    if not bedrooms:
        cprint("\n3. Bedrooms:")
        cprint("   a. All Bedrooms | 0. Studio | 1. 1 Bed | 2. 2 Beds | 3. 3 Beds | 4. 4 Beds | 5. 5+ Beds")
        bedrooms = input(f"{GREEN}Choice (a, 0-5, default a): {RESET}").strip().lower() or "a"

    max_listings = args.max_listings
    if max_listings is None:
        listings_input = input(f"\n{GREEN}4. How many listings to grab? (Press ENTER for ALL): {RESET}").strip()
        try:
            max_listings = int(listings_input) if listings_input and int(listings_input) > 0 else None
        except ValueError:
            max_listings = None

    target_url = build_bayut_url(purpose, bedrooms, loc_path)

    return ScrapeConfig(
        purpose_str="For Rent" if purpose == "2" else "For Sale",
        location=resolved_name,
        bedrooms_label=BEDROOM_LABELS.get(bedrooms, "All Bedrooms"),
        max_listings=max_listings,
        target_url=target_url,
    )


def handle_captcha(page: ChromiumPage) -> None:
    if any(term in page.title or term in page.html for term in ["Just a moment...", "cf-challenge", "Verify you are human"]):
        cprint("\n" + "!" * 60)
        cprint("⚠️  [CAPTCHA DETECTED] Complete the verification in the browser...")
        cprint("!" * 60 + "\n")
        while any(term in page.title or term in page.html for term in ["Just a moment...", "cf-challenge", "Verify you are human"]):
            time.sleep(2)
        cprint("✅ Verification cleared!\n")


# ==========================================
# STRUCTURED-DATA EXTRACTION (the "smart" core)
# ==========================================
def extract_next_data(html_content: str) -> Optional[Dict[str, Any]]:
    """Pull Bayut's embedded __NEXT_DATA__ JSON payload, if present."""
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html_content, re.DOTALL,
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None

    page_props = data.get("props", {}).get("pageProps", {})
    for key in ("property", "propertyData", "listing", "propertyDetails"):
        prop = page_props.get(key)
        if isinstance(prop, dict) and prop:
            return prop
    return None


def dig(d: Optional[Dict[str, Any]], *path: str, default: Any = None) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def build_location_hierarchy(prop: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    """
    Bayut exposes a 'location' array ordered from most specific to least
    specific (e.g. [Tower, Sub-Community, Community, City, Country]) or the
    reverse depending on payload version — handle both by tagging on 'level'
    when present, otherwise assume specific -> general.
    """
    loc = prop.get("location")
    levels: Dict[int, str] = {}
    if isinstance(loc, list) and loc:
        for entry in loc:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("value")
            level = entry.get("level")
            if name is None:
                continue
            if level is not None:
                levels[level] = name
        if levels:
            ordered = [levels[k] for k in sorted(levels.keys())]
        else:
            ordered = [e.get("name") for e in loc if isinstance(e, dict) and e.get("name")]
        ordered = list(dict.fromkeys(ordered))  # de-dup, preserve order
        full = " > ".join(ordered)
        city = ordered[-1] if ordered else "N/A"
        community = ordered[-2] if len(ordered) >= 2 else "N/A"
        sub_community = ordered[-3] if len(ordered) >= 3 else "N/A"
        tower = ordered[0] if len(ordered) >= 4 else "N/A"
        return full or "N/A", city, community, sub_community, tower
    return "N/A", "N/A", "N/A", "N/A", "N/A"


def clean_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = re.sub(r"[^\d.]", "", str(value))
    if not s:
        return None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def extract_from_json(prop: Dict[str, Any], prop_url: str, config: ScrapeConfig) -> Dict[str, Any]:
    price = clean_number(prop.get("price"))
    area = clean_number(dig(prop, "area") or dig(prop, "coveredArea") or dig(prop, "plotArea"))
    beds = prop.get("rooms")
    beds = "Studio" if str(beds) in ("0", "0.0") else clean_number(beds)
    baths = clean_number(prop.get("baths"))
    permit = prop.get("permitNumber") or prop.get("rera") or dig(prop, "extraFields", "permitNumber") or "N/A"
    reference = prop.get("referenceNumber") or prop.get("externalID") or "N/A"
    title = prop.get("title") or "Property Listing"
    completion = prop.get("completionStatus") or dig(prop, "extraFields", "completionStatus") or "N/A"
    furnishing = prop.get("furnishingStatus") or "N/A"
    agency = dig(prop, "agency", "name") or "N/A"
    agent_phone = dig(prop, "phoneNumber") or dig(prop, "contactName") or "N/A"
    lat = dig(prop, "geography", "lat")
    lng = dig(prop, "geography", "lng")
    cover_photo = prop.get("coverPhoto", {})
    cover_url = cover_photo.get("url") if isinstance(cover_photo, dict) else "N/A"
    listed_ts = prop.get("createdAt") or prop.get("updatedAt")
    listed_date = "N/A"
    if listed_ts:
        try:
            listed_date = datetime.fromtimestamp(int(listed_ts)).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            listed_date = "N/A"

    full_loc, city, community, sub_community, tower = build_location_hierarchy(prop)
    price_per_sqft = round(price / area, 2) if price and area else None
    resolved_location = full_loc if full_loc != "N/A" else config.location

    return {
        "Property URL": prop_url,
        "Title": title,
        "Price (AED)": price,
        "Price / sqft (AED)": price_per_sqft,
        "Bedrooms": beds,
        "Bathrooms": baths,
        "Area (sqft)": area,
        "Permit Number": permit,
        "Reference No.": reference,
        "Full Location": resolved_location,
        "Location Match": "✅ Match" if location_matches(resolved_location, config.location) else "⚠️ Mismatch",
        "City": city,
        "Community": community,
        "Sub-Community": sub_community,
        "Tower/Building": tower,
        "Completion Status": completion,
        "Furnishing": furnishing,
        "Agency": agency,
        "Agent Contact": agent_phone,
        "Listed Date": listed_date,
        "Latitude": lat if lat is not None else "N/A",
        "Longitude": lng if lng is not None else "N/A",
        "Cover Photo": cover_url or "N/A",
        "Purpose": config.purpose_str,
    }


def _visible_text(html: str) -> str:
    """Strip script/style content and tags so regexes only see what a user
    would actually see — not JS bundles, JSON blobs, or attribute values
    that happen to contain stray digits next to unrelated words."""
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def extract_from_regex_fallback(page: ChromiumPage, full_html: str, prop_url: str, config: ScrapeConfig) -> Dict[str, Any]:
    """Scoped fallback if __NEXT_DATA__ isn't found — still safer than the
    original whole-page regex because we search inside the details card,
    and only over visible text (not raw HTML/script content, which is what
    previously let a stray "202" match as a bedroom count)."""
    card = page.ele("css:div[aria-label='Property details'], div[class*='details'], main", timeout=1)
    scope_html = card.html if card else full_html
    scope_text = _visible_text(scope_html)

    price: Any = "N/A"
    price_match = re.search(r"AED\s*([\d,]+)(?!\d)", scope_text)
    if price_match:
        price = clean_number(price_match.group(1))

    beds: Any = "N/A"
    # capped at 2 digits (no real listing has 100+ bedrooms) and requires a
    # spelled-out "Bed(room)(s)" or "B/R" — bare "BR" alone was too generic
    # and matched unrelated reference codes elsewhere on the page.
    beds_match = re.search(r"\b(\d{1,2}|Studio)\s*(?:Bedrooms?|Beds?|B\s*/\s*R)\b", scope_text, re.IGNORECASE)
    if beds_match:
        beds = beds_match.group(1)

    baths: Any = "N/A"
    baths_match = re.search(r"\b(\d{1,2})\s*(?:Bathrooms?|Baths?)\b", scope_text, re.IGNORECASE)
    if baths_match:
        baths = clean_number(baths_match.group(1))

    area: Any = "N/A"
    area_match = re.search(r"([\d,]+)\s*sqft", scope_text, re.IGNORECASE)
    if area_match:
        area = clean_number(area_match.group(1))

    permit = "N/A"
    permit_label_match = re.search(
        r'Permit\s*Number[^0-9]{0,20}(\d{6,12})', scope_text, re.IGNORECASE,
    )
    if permit_label_match:
        permit = permit_label_match.group(1)

    title = "Property Listing"
    h1_el = page.ele("tag:h1", timeout=0.5)
    if h1_el:
        title = h1_el.text.strip()

    location = config.location
    bread_el = page.eles("css:a[href*='/for-sale/'], a[href*='/to-rent/']")
    if len(bread_el) >= 2:
        for el in reversed(bread_el):
            text = el.text.strip()
            if text and text.lower() not in ("villas", "townhouses", "apartments", "for sale", "to rent"):
                location = text
                break

    price_per_sqft = round(price / area, 2) if isinstance(price, (int, float)) and isinstance(area, (int, float)) and area else None

    return {
        "Property URL": prop_url,
        "Title": title,
        "Price (AED)": price,
        "Price / sqft (AED)": price_per_sqft,
        "Bedrooms": beds,
        "Bathrooms": baths,
        "Area (sqft)": area,
        "Permit Number": permit,
        "Reference No.": "N/A",
        "Full Location": location,
        "Location Match": "✅ Match" if location_matches(location, config.location) else "⚠️ Mismatch",
        "City": "N/A",
        "Community": location,
        "Sub-Community": "N/A",
        "Tower/Building": "N/A",
        "Completion Status": "N/A",
        "Furnishing": "N/A",
        "Agency": "N/A",
        "Agent Contact": "N/A",
        "Listed Date": "N/A",
        "Latitude": "N/A",
        "Longitude": "N/A",
        "Cover Photo": "N/A",
        "Purpose": config.purpose_str,
    }


# ==========================================
# TRAKHEESI / DLD PERMIT VERIFICATION
# ------------------------------------------
# Every Bayut listing shows a Trakheesi (Dubai Land Department) permit
# number next to a QR code. The QR encodes a link to DLD's own "Real
# Estate Permit Card" verification page — NOT an individual agent's name
# or phone number (DLD doesn't publish that), just the licensed brokerage
# company and its RERA license number, plus permit/property details.
# Confirmed against two live examples (a land/sale permit and a rental
# unit permit), which have slightly different field sets:
#   Listing Details:       Transaction Number, Listing Number, End Date
#   Authority Information: License #, Authority Name  (= the brokerage)
#   Property Details:      Property Name, [Building Name], Property Type,
#                           Property Size(Sqm), Zone Name,
#                           Property Value(AED), Permit Type,
#                           [Rooms Count, Room Type]  (rental units only)
# followed by page footer boilerplate ("Report violation", "Feedback",
# "Call Us: ...") that must be excluded, not captured as a field value.
# Extraction works by finding each known label in the flattened page text
# and taking everything up to whichever other known label/boundary comes
# next — robust to blank values (e.g. "Property Name" is sometimes empty).
# ==========================================
TRAKHEESI_FIELD_LABELS: List[Tuple[str, str]] = [
    ("Transaction Number", "Trakheesi Transaction No."),
    ("Listing Number", "Trakheesi Listing No."),
    ("End Date", "Trakheesi Permit End Date"),
    ("License #", "Trakheesi License No."),
    ("Authority Name", "Trakheesi Authority Name"),
    ("Property Name", "Trakheesi Property Name"),
    ("Building Name", "Trakheesi Building Name"),
    ("Property Type", "Trakheesi Property Type"),
    ("Property Size(Sqm)", "Trakheesi Property Size (Sqm)"),
    ("Zone Name", "Trakheesi Zone Name"),
    ("Property Value(AED)", "Trakheesi Property Value (AED)"),
    ("Permit Type", "Trakheesi Permit Type"),
    ("Rooms Count", "Trakheesi Rooms Count"),
    ("Room Type", "Trakheesi Room Type"),
]
TRAKHEESI_NUMERIC_FIELDS = {
    "Trakheesi Property Size (Sqm)", "Trakheesi Property Value (AED)", "Trakheesi Rooms Count",
}
# Section headings and footer boilerplate aren't fields themselves, but
# must also act as stop-boundaries so e.g. "Authority Name" doesn't
# swallow the next section's heading, or "Permit Type" doesn't swallow
# the page footer, into its captured value.
TRAKHEESI_SECTION_HEADERS = [
    "Listing Details", "Authority Information", "Property Details",
    "Report violation", "Feedback", "Call Us", "dubailand.gov.ae",
]


def _blank_trakheesi_fields() -> Dict[str, Any]:
    fields: Dict[str, Any] = {"Trakheesi URL": "N/A", "Trakheesi Verified": "N/A"}
    for _, out_label in TRAKHEESI_FIELD_LABELS:
        fields[out_label] = "N/A"
    return fields


def find_trakheesi_url(prop_json: Optional[Dict[str, Any]], full_html: str) -> Optional[str]:
    """Look for a DLD/Trakheesi verification link, first inside the
    structured JSON payload (any string field that points at
    dubailand.gov.ae or mentions trakheesi), then as a fallback scan the
    raw HTML for the same thing near the QR/permit badge."""
    def scan(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for v in obj.values():
                found = scan(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = scan(item)
                if found:
                    return found
        elif isinstance(obj, str):
            low = obj.lower()
            if obj.startswith("http") and ("dubailand.gov.ae" in low or "trakheesi" in low):
                return obj
        return None

    if prop_json:
        url = scan(prop_json)
        if url:
            return url

    match = re.search(
        r'href=["\'](https?://[^"\']*(?:dubailand\.gov\.ae|trakheesi)[^"\']*)["\']',
        full_html, re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(r'(https?://dubailand\.gov\.ae/[^"\'\s<>]+)', full_html, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


# The DLD/Dubai Now site shows a promo modal ("The Digital Sale service is
# now available on the Dubai Now app...") over the permit page that has to
# be dismissed before the real content is reachable. We don't know its
# exact markup (no live access to test against), so try a broad set of
# common close-button patterns rather than one fixed selector.
POPUP_CLOSE_SELECTORS = [
    "css:[aria-label='Close']",
    "css:[aria-label='close']",
    "css:button.close",
    "css:[class*='close-icon']",
    "css:[class*='CloseIcon']",
    "css:[class*='modal'] [class*='close']",
    "xpath://button[normalize-space(text())='×' or normalize-space(text())='✕' or normalize-space(text())='X']",
    "xpath://*[@role='dialog']//button[1]",
]


def dismiss_popups(page: ChromiumPage, attempts: int = 2) -> None:
    for _ in range(attempts):
        closed_any = False
        for selector in POPUP_CLOSE_SELECTORS:
            try:
                el = page.ele(selector, timeout=0.4)
                if el:
                    el.click()
                    time.sleep(0.5)
                    closed_any = True
            except Exception:
                continue
        if not closed_any:
            break


def extract_trakheesi_details(page: ChromiumPage, trakheesi_url: str) -> Dict[str, Any]:
    result = _blank_trakheesi_fields()
    result["Trakheesi URL"] = trakheesi_url
    try:
        page.get(trakheesi_url)
        time.sleep(1.5)
        dismiss_popups(page)
        text = re.sub(r"<[^>]+>", " ", page.html)
        text = re.sub(r"\s+", " ", text).strip()

        if "verified by dubai land department" in text.lower():
            result["Trakheesi Verified"] = "✅ Verified by DLD"

        raw_labels = [raw for raw, _ in TRAKHEESI_FIELD_LABELS] + TRAKHEESI_SECTION_HEADERS
        for raw_label, out_label in TRAKHEESI_FIELD_LABELS:
            start_match = re.search(re.escape(raw_label), text, re.IGNORECASE)
            if not start_match:
                continue
            start = start_match.end()

            next_positions = []
            for other_label in raw_labels:
                if other_label == raw_label:
                    continue
                m2 = re.search(re.escape(other_label), text[start:], re.IGNORECASE)
                if m2:
                    next_positions.append(start + m2.start())
            end = min(next_positions) if next_positions else min(start + 120, len(text))

            value = text[start:end].strip(" :.- ")
            if value:
                if out_label in TRAKHEESI_NUMERIC_FIELDS:
                    numeric_value = clean_number(value)
                    result[out_label] = numeric_value if numeric_value is not None else value
                else:
                    result[out_label] = value
    except Exception as exc:
        logger.debug("Trakheesi lookup failed for %s: %s", trakheesi_url, exc)
    return result


def collect_property_urls(page: ChromiumPage, config: ScrapeConfig) -> List[str]:
    all_property_urls: List[str] = []
    seen_urls = set()
    current_page = 1
    current_url = config.target_url
    max_listings = config.max_listings

    while True:
        logger.info("Collecting links from Search Page %d...", current_page)
        page.get(current_url)
        time.sleep(1.2)
        handle_captcha(page)
        cards = page.eles("css:div[aria-label='Listing'], article, li[role='article']")
        if not cards:
            break

        page_urls_found = 0
        for card in cards:
            try:
                card_html = card.html.lower()
                if "similar" in card_html or "recommend" in card_html:
                    continue
                link_el = card.ele("css:a[href*='details-']", timeout=0.5)
                if not link_el:
                    continue
                href = link_el.attr("href") or ""
                full_url = f"https://www.bayut.com{href}" if href.startswith("/") else href
                if full_url and "details-" in full_url and full_url not in seen_urls:
                    seen_urls.add(full_url)
                    all_property_urls.append(full_url)
                    page_urls_found += 1
                    if max_listings and len(all_property_urls) >= max_listings:
                        break
            except Exception as exc:
                logger.debug("Skipped a listing card: %s", exc)
                continue

        if max_listings and len(all_property_urls) >= max_listings:
            break
        if page_urls_found == 0:
            break

        current_page += 1
        if "/page-" in current_url:
            current_url = re.sub(r"page-\d+/", f"page-{current_page}/", current_url)
        else:
            current_url = current_url.rstrip("/") + f"/page-{current_page}/"

    return all_property_urls


def extract_property(
    page: ChromiumPage, prop_url: str, config: ScrapeConfig,
    retries: int = 2, verify_trakheesi: bool = True,
) -> Optional[Dict[str, Any]]:
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            page.get(prop_url)
            time.sleep(random.uniform(0.8, 1.3))
            handle_captcha(page)
            page.scroll.down(1200)
            time.sleep(0.5)
            full_html = page.html

            prop_json = extract_next_data(full_html)
            if prop_json:
                record = extract_from_json(prop_json, prop_url, config)
            else:
                record = extract_from_regex_fallback(page, full_html, prop_url, config)

            if verify_trakheesi:
                trakheesi_url = find_trakheesi_url(prop_json, full_html)
                if trakheesi_url:
                    record.update(extract_trakheesi_details(page, trakheesi_url))
                else:
                    record.update(_blank_trakheesi_fields())
            else:
                record.update(_blank_trakheesi_fields())

            return record
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                logger.debug("Retry %d/%d for %s (%s)", attempt + 1, retries, prop_url, exc)
                time.sleep(1.0)
                continue

    logger.warning("Failed to extract %s after %d attempts: %s", prop_url, retries + 1, last_exc)
    return None


def add_value_ratings(df: pd.DataFrame) -> pd.DataFrame:
    """Classify each listing's price/sqft against the dataset's own
    distribution so a reader can spot deals at a glance."""
    numeric = df["Price / sqft (AED)"].apply(lambda v: v if isinstance(v, (int, float)) else None)
    valid = numeric.dropna()

    if len(valid) >= 3:
        low, high = valid.quantile(0.33), valid.quantile(0.66)

        def rate(v: Any) -> str:
            if not isinstance(v, (int, float)):
                return "N/A"
            if v <= low:
                return "🟢 Great Value"
            if v <= high:
                return "🟡 Fair Price"
            return "🔴 Premium"

        df["Value Rating"] = numeric.apply(rate)
    else:
        df["Value Rating"] = "N/A"
    return df


# ==========================================
# PROFESSIONAL EXCEL REPORT
# ==========================================
def _style_header_cell(cell, fill_color: str = BRAND_BLUE) -> None:
    cell.fill = PatternFill("solid", fgColor=fill_color)
    cell.font = Font(bold=True, color="FFFFFF")
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_cover_sheet(wb, df: pd.DataFrame, config: ScrapeConfig) -> None:
    ws = wb.create_sheet("Cover")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("B2:H4")
    title = ws["B2"]
    title.value = "BAYUT MARKET REPORT"
    title.font = Font(size=26, bold=True, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor=BRAND_NAVY)
    title.alignment = Alignment(horizontal="center", vertical="center")
    for row in ws["B2:H4"]:
        for cell in row:
            cell.fill = PatternFill("solid", fgColor=BRAND_NAVY)

    ws.merge_cells("B5:H5")
    subtitle = ws["B5"]
    subtitle.value = f"{config.location}  •  {config.purpose_str}  •  Prepared by Oussama's Smart Scraper"
    subtitle.font = Font(size=12, italic=True, color=BRAND_GOLD)
    subtitle.fill = PatternFill("solid", fgColor=BRAND_NAVY)
    subtitle.alignment = Alignment(horizontal="center", vertical="center")

    for r in range(2, 6):
        ws.row_dimensions[r].height = 24 if r != 5 else 20

    criteria = [
        ("Location", config.location),
        ("Purpose", config.purpose_str),
        ("Bedrooms", config.bedrooms_label),
        ("Requested Max Listings", config.max_listings or "All available"),
        ("Total Listings Captured", len(df)),
        ("Report Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    start_row = 8
    ws.cell(row=start_row - 1, column=2, value="Search Criteria").font = Font(size=13, bold=True, color=BRAND_NAVY)
    thin_border = Border(*(Side(style="thin", color="B7B7B7"),) * 4)
    for i, (label, value) in enumerate(criteria):
        r = start_row + i
        label_cell = ws.cell(row=r, column=2, value=label)
        value_cell = ws.cell(row=r, column=3, value=value)
        label_cell.font = Font(bold=True, color=BRAND_NAVY)
        label_cell.fill = PatternFill("solid", fgColor=BRAND_LIGHT)
        label_cell.border = thin_border
        value_cell.border = thin_border
        ws.merge_cells(start_row=r, start_column=3, end_row=r, end_column=5)

    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 24
    for col in "CDEFGH":
        ws.column_dimensions[col].width = 16


def _write_dashboard_sheet(wb, df: pd.DataFrame, config: ScrapeConfig) -> None:
    ws = wb.create_sheet("Dashboard")
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    header = ws["A1"]
    header.value = "Key Metrics"
    header.font = Font(size=16, bold=True, color="FFFFFF")
    header.fill = PatternFill("solid", fgColor=BRAND_NAVY)
    header.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    price_numeric = df["Price (AED)"].apply(lambda v: v if isinstance(v, (int, float)) else None).dropna()
    area_numeric = df["Area (sqft)"].apply(lambda v: v if isinstance(v, (int, float)) else None).dropna()
    ppsf_numeric = df["Price / sqft (AED)"].apply(lambda v: v if isinstance(v, (int, float)) else None).dropna()

    tiles = [
        ("Total Listings", len(df)),
        ("Average Price (AED)", f"{price_numeric.mean():,.0f}" if len(price_numeric) else "N/A"),
        ("Min Price (AED)", f"{price_numeric.min():,.0f}" if len(price_numeric) else "N/A"),
        ("Max Price (AED)", f"{price_numeric.max():,.0f}" if len(price_numeric) else "N/A"),
        ("Avg Price / sqft (AED)", f"{ppsf_numeric.mean():,.0f}" if len(ppsf_numeric) else "N/A"),
        ("Average Area (sqft)", f"{area_numeric.mean():,.0f}" if len(area_numeric) else "N/A"),
    ]
    tile_col = 1
    for label, value in tiles:
        col_letter = get_column_letter(tile_col)
        next_col_letter = get_column_letter(tile_col + 1)
        ws.merge_cells(f"{col_letter}3:{next_col_letter}3")
        ws.merge_cells(f"{col_letter}4:{next_col_letter}4")
        label_cell = ws[f"{col_letter}3"]
        label_cell.value = label
        label_cell.font = Font(size=9, bold=True, color="FFFFFF")
        label_cell.fill = PatternFill("solid", fgColor=BRAND_BLUE)
        label_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        value_cell = ws[f"{col_letter}4"]
        value_cell.value = value
        value_cell.font = Font(size=14, bold=True, color=BRAND_NAVY)
        value_cell.fill = PatternFill("solid", fgColor=BRAND_LIGHT)
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        tile_col += 2
    ws.row_dimensions[3].height = 28
    ws.row_dimensions[4].height = 24

    # --- Chart 1: Average price by bedroom count ---
    bed_table_row = 7
    ws.cell(row=bed_table_row, column=1, value="Bedrooms").font = Font(bold=True)
    ws.cell(row=bed_table_row, column=2, value="Avg Price (AED)").font = Font(bold=True)
    priced = df[df["Price (AED)"].apply(lambda v: isinstance(v, (int, float)))]
    if len(priced):
        bed_avg = (
            priced.assign(_bed=priced["Bedrooms"].astype(str))
            .groupby("_bed")["Price (AED)"].mean().round(0).sort_index()
        )
        for i, (bed_label, avg_price) in enumerate(bed_avg.items(), start=1):
            ws.cell(row=bed_table_row + i, column=1, value=bed_label)
            ws.cell(row=bed_table_row + i, column=2, value=float(avg_price))
        bed_rows = len(bed_avg)

        bar = BarChart()
        bar.title = "Average Price by Bedrooms"
        bar.y_axis.title = "AED"
        bar.x_axis.title = "Bedrooms"
        bar.style = 10
        data_ref = Reference(ws, min_col=2, min_row=bed_table_row, max_row=bed_table_row + bed_rows)
        cats_ref = Reference(ws, min_col=1, min_row=bed_table_row + 1, max_row=bed_table_row + bed_rows)
        bar.add_data(data_ref, titles_from_data=True)
        bar.set_categories(cats_ref)
        bar.width, bar.height = 16, 9
        ws.add_chart(bar, "D7")

    # --- Chart 2: Listings by community ---
    community_table_row = bed_table_row + 12
    ws.cell(row=community_table_row, column=1, value="Community").font = Font(bold=True)
    ws.cell(row=community_table_row, column=2, value="Listings").font = Font(bold=True)
    community_counts = df[df["Community"] != "N/A"]["Community"].value_counts().head(8)
    if len(community_counts):
        for i, (community, count) in enumerate(community_counts.items(), start=1):
            ws.cell(row=community_table_row + i, column=1, value=community)
            ws.cell(row=community_table_row + i, column=2, value=int(count))
        comm_rows = len(community_counts)

        pie = PieChart()
        pie.title = "Listings by Community"
        data_ref = Reference(ws, min_col=2, min_row=community_table_row, max_row=community_table_row + comm_rows)
        cats_ref = Reference(ws, min_col=1, min_row=community_table_row + 1, max_row=community_table_row + comm_rows)
        pie.add_data(data_ref, titles_from_data=True)
        pie.set_categories(cats_ref)
        pie.width, pie.height = 16, 9
        ws.add_chart(pie, f"D{community_table_row}")

    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 16


# The main "Listings" sheet only shows the columns an agent actually
# scans while browsing — everything else (Trakheesi legal/permit detail,
# coordinates, raw agency contact, cover photo) lives on "Full Details",
# joined by Permit Number / Property URL. Cramming all ~36 columns into
# one sheet made it unreadable, which is what this fixes.
CORE_LISTING_COLUMNS = [
    "Title", "Price (AED)", "Price / sqft (AED)", "Value Rating", "Bedrooms", "Bathrooms",
    "Area (sqft)", "Full Location", "Location Match", "Completion Status", "Furnishing",
    "Permit Number", "Trakheesi Verified", "Trakheesi Authority Name", "Purpose", "Property URL",
]


def _write_data_sheet(wb, sheet_name: str, df: pd.DataFrame, config: ScrapeConfig, table_name: str):
    ws = wb.create_sheet(sheet_name)
    n_rows, n_cols = df.shape
    last_col_letter = get_column_letter(n_cols)
    col_names = list(df.columns)

    # --- Title banner ---
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    title_cell = ws.cell(row=1, column=1)
    title_cell.value = (
        f"Bayut {config.purpose_str} — {config.location}  "
        f"({n_rows} listings, generated {datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
    title_cell.font = Font(size=14, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor=BRAND_NAVY)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26

    # --- Header row ---
    header_row = 2
    for c, col_name in enumerate(col_names, start=1):
        cell = ws.cell(row=header_row, column=c, value=col_name)
        _style_header_cell(cell)
    ws.row_dimensions[header_row].height = 24

    # --- Data rows: values, banding, borders, number formats, hyperlinks ---
    thin_border = Border(*(Side(style="thin", color="B7B7B7"),) * 4)
    band_fill = PatternFill("solid", fgColor=BRAND_LIGHT)
    currency_cols = {"Price (AED)", "Price / sqft (AED)", "Trakheesi Property Value (AED)"}
    number_cols = {"Area (sqft)", "Bathrooms", "Bedrooms", "Latitude", "Longitude", "Trakheesi Property Size (Sqm)"}

    for r, (_, row) in enumerate(df.iterrows()):
        excel_row = header_row + 1 + r
        for c, col_name in enumerate(col_names, start=1):
            value = row[col_name]
            cell = ws.cell(row=excel_row, column=c, value=value)
            cell.border = thin_border
            if r % 2 == 1:
                cell.fill = band_fill
            if col_name in currency_cols and isinstance(value, (int, float)):
                cell.number_format = '#,##0 "AED"'
            elif col_name in number_cols and isinstance(value, (int, float)):
                cell.number_format = "#,##0"
            if col_name == "Property URL" and value:
                cell.hyperlink = value
                cell.font = Font(color="1155CC", underline="single")

    # --- Freeze header, autofilter, column widths ---
    ws.freeze_panes = f"A{header_row + 1}"
    ws.auto_filter.ref = f"A{header_row}:{last_col_letter}{header_row + n_rows}"

    for c, col_name in enumerate(col_names, start=1):
        max_len = max([len(str(col_name))] + [len(str(v)) for v in df[col_name].astype(str).tolist()])
        ws.column_dimensions[get_column_letter(c)].width = min(max(12, max_len + 2), 55)

    table = Table(displayName=table_name, ref=f"A{header_row}:{last_col_letter}{header_row + n_rows}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium9", showRowStripes=False,
        showFirstColumn=False, showLastColumn=False, showColumnStripes=False,
    )
    ws.add_table(table)

    # --- Conditional formatting: green (cheap) -> red (expensive) per sqft ---
    if "Price / sqft (AED)" in col_names:
        ppsf_col = get_column_letter(col_names.index("Price / sqft (AED)") + 1)
        rng = f"{ppsf_col}{header_row + 1}:{ppsf_col}{header_row + n_rows}"
        ws.conditional_formatting.add(
            rng,
            ColorScaleRule(
                start_type="min", start_color="63BE7B",
                mid_type="percentile", mid_value=50, mid_color="FFEB84",
                end_type="max", end_color="F8696B",
            ),
        )

    return ws


def write_professional_excel(df: pd.DataFrame, out_path: str, config: ScrapeConfig) -> None:
    df = add_value_ratings(df)

    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)  # drop the default blank sheet

    _write_cover_sheet(wb, df, config)
    _write_dashboard_sheet(wb, df, config)

    core_cols = [c for c in CORE_LISTING_COLUMNS if c in df.columns]
    _write_data_sheet(wb, "Listings", df[core_cols], config, table_name="Listings")
    _write_data_sheet(wb, "Full Details", df, config, table_name="FullDetails")

    wb.active = wb.sheetnames.index("Listings")
    wb.save(out_path)


def run_search(page: ChromiumPage, args: argparse.Namespace) -> None:
    config = get_user_inputs(args, page=page)
    logger.info("[1/3] Target URL: %s", config.target_url)

    all_property_urls = collect_property_urls(page, config)
    logger.info("[2/3] Collected %d links. Extracting structured details...", len(all_property_urls))

    all_properties: List[Dict[str, Any]] = []
    for idx, prop_url in enumerate(all_property_urls, 1):
        record = extract_property(page, prop_url, config, verify_trakheesi=args.verify_trakheesi)
        if record:
            all_properties.append(record)
            logger.info(
                "[%d/%d] Extracted -> Permit: %s | Price: %s | Location: %s (%s) | DLD: %s | Brokerage: %s",
                idx, len(all_property_urls), record["Permit Number"], record["Price (AED)"],
                record["Full Location"], record["Location Match"],
                record["Trakheesi Verified"], record["Trakheesi Authority Name"],
            )
        else:
            logger.warning("[%d/%d] Failed after retries, skipped.", idx, len(all_property_urls))

    if not all_properties:
        logger.warning("No listings extracted.")
        return

    df = pd.DataFrame(all_properties)
    df.drop_duplicates(subset=["Property URL"], inplace=True)

    mismatches = int((df["Location Match"] == "⚠️ Mismatch").sum())
    if len(df) and mismatches / len(df) > 0.5:
        logger.warning("=" * 70)
        logger.warning(
            "⚠️  %d of %d listings do NOT match the requested location '%s'.",
            mismatches, len(df), config.location,
        )
        logger.warning("    The Bayut URL slug guessed for this project may be wrong: %s", config.target_url)
        logger.warning("    Open that URL in your browser — if it 404s or redirects, try a broader")
        logger.warning("    area name (e.g. the parent community) instead of this specific project.")
        logger.warning("=" * 70)

    if args.out:
        full_path = args.out
    else:
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(desktop_path, exist_ok=True)
        file_name = f"bayut_{config.location.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        full_path = os.path.join(desktop_path, file_name)

    write_professional_excel(df, full_path, config)
    logger.info("[3/3] DONE! Saved %d listings to: %s", len(df), full_path)


def blank_args(headless: bool, verify_trakheesi: bool) -> argparse.Namespace:
    """Fresh, unset args for subsequent loop runs so the user is re-prompted
    for every field instead of the first run's CLI flags sticking around.
    headless/verify_trakheesi are session-level settings, so they persist."""
    return argparse.Namespace(
        purpose=None, location=None, bedrooms=None, max_listings=None,
        headless=headless, out=None, verify_trakheesi=verify_trakheesi,
    )


def scrape_bayut() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose, log_file=args.log_file)

    co = ChromiumOptions()
    co.no_imgs(True)
    if args.headless:
        co.headless(True)
    page = ChromiumPage(co)

    try:
        run_args = args
        while True:
            run_search(page, run_args)

            cprint("\n" + "=" * 70)
            choice = input(
                f"{GREEN}Press ENTER (or 1) to run another search, or 2 to close the script: {RESET}"
            ).strip()
            if choice == "2":
                cprint("\n👋 Closing. Goodbye!")
                break
            run_args = blank_args(args.headless, args.verify_trakheesi)
    finally:
        page.quit()


if __name__ == "__main__":
    scrape_bayut()
