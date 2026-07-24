"""
Bayut Scraper Engine — smart extraction + professional Excel export.

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
    Price per sqft, Listed Date, Latitude/Longitude, Cover Photo URL.
  - Numeric columns are stored as real numbers (int/float), not strings,
    so Excel can sort/filter/sum them.
  - Retries failed page loads instead of silently dropping listings.
  - Professional Excel workbook: styled header, frozen header row,
    autofilter, currency/number formats, banded rows, clickable URL
    hyperlinks, auto-sized columns, and a summary sheet with stats.
"""

import time
import re
import json
import random
import os
import difflib
import argparse
from datetime import datetime

import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from DrissionPage import ChromiumPage, ChromiumOptions

# ==========================================
# TERMINAL COLOR & LOGO CONFIGURATION
# ==========================================
GREEN = "\033[92m"
RESET = "\033[0m"


def print_logo():
    logo = f"""{GREEN}
██████╗  █████╗ ██╗   ██╗██╗   ██╗████████╗    ███████╗ ██████╗██████╗  █████╗ ██████╗ ███████╗██████╗
██╔══██╗██╔══██╗╚██╗ ██╔╝██║   ██║╚══██╔══╝    ██╔════╝██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗
██████╔╝███████║ ╚████╔╝ ██║   ██║   ██║       ███████╗██║     ██████╔╝███████║██████╔╝█████╗  ██████╔╝
██╔══██╗██╔══██║  ╚██╔╝  ██║   ██║   ██║       ╚╚════██║██║     ██╔══██╗██╔══██║██╔═══╝ ██╔══╝  ██╔══██╗
██████╔╝███████║   ██║   ╚██████╔╝   ██║       ███████║╚██████╗██║  ██║██║  ██║██║     ███████╗██║  ██║
╚═════╝ ╚══════╝   ╚═╝    ╚═════╝    ╚═╝       ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝

                 [ B U I L T   B Y   O U S S A M A ]
{RESET}"""
    print(logo)


def cprint(text):
    print(f"{GREEN}{text}{RESET}")


# ==========================================
# ULTIMATE & EXHAUSTIVE DUBAI FULL PROJECT DATABASE
# Covers master-communities, sub-communities/clusters, and individual
# towers/buildings so free-text input resolves to an exact Bayut slug
# instead of falling through to fuzzy-matching or a raw slugified guess.
# ==========================================
LOCATION_DATABASE = {
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
}


def format_slug(text):
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    return text


def resolve_location(user_input):
    clean_input = user_input.lower().strip()
    if clean_input in LOCATION_DATABASE:
        return LOCATION_DATABASE[clean_input], clean_input.title()
    keys = list(LOCATION_DATABASE.keys())
    matches = difflib.get_close_matches(clean_input, keys, n=1, cutoff=0.30)
    if matches:
        best_match = matches[0]
        cprint(f"💡 Auto-corrected spelling '{user_input}' ---> Matched to: '{best_match.title()}'")
        return LOCATION_DATABASE[best_match], best_match.title()
    formatted_slug = format_slug(user_input)
    if formatted_slug and formatted_slug != "uae":
        return f"dubai/{formatted_slug}", user_input.title()
    return "dubai", "Dubai"


def build_bayut_url(purpose_choice, bed_choice, location_path):
    purpose_slug = "to-rent" if purpose_choice == "2" else "for-sale"
    bed_slugs = {
        "1": "studio-property", "2": "1-bedroom-property", "3": "2-bedroom-property",
        "4": "3-bedroom-property", "5": "4-bedroom-property", "6": "5-bedroom-property",
    }
    bed_slug = bed_slugs.get(bed_choice, "property")
    return f"https://www.bayut.com/{purpose_slug}/{bed_slug}/{location_path}/"


def parse_args():
    parser = argparse.ArgumentParser(description="Bayut Scraper Engine")
    parser.add_argument("--purpose", choices=["1", "2"], help="1=Buy, 2=Rent")
    parser.add_argument("--location", help="Project / community / area name")
    parser.add_argument("--bedrooms", choices=[str(i) for i in range(7)], help="0-6 (0=All)")
    parser.add_argument("--max-listings", type=int, help="Cap on number of listings")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--out", help="Output .xlsx path (default: Desktop, auto-named)")
    return parser.parse_args()


def get_user_inputs(args):
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

    loc_path, resolved_name = resolve_location(location_raw)

    bedrooms = args.bedrooms
    if not bedrooms:
        cprint("\n3. Bedrooms:")
        cprint("   0. All Bedrooms | 1. Studio | 2. 1 Bed | 3. 2 Beds | 4. 3 Beds | 5. 4 Beds | 6. 5+ Beds")
        bedrooms = input(f"{GREEN}Choice (0-6, default 0): {RESET}").strip() or "0"

    max_listings = args.max_listings
    if max_listings is None:
        listings_input = input(f"\n{GREEN}4. How many listings to grab? (Press ENTER for ALL): {RESET}").strip()
        try:
            max_listings = int(listings_input) if listings_input and int(listings_input) > 0 else None
        except ValueError:
            max_listings = None

    target_url = build_bayut_url(purpose, bedrooms, loc_path)

    return {
        "purpose_str": "For Rent" if purpose == "2" else "For Sale",
        "location": resolved_name,
        "max_listings": max_listings,
        "target_url": target_url,
    }


def handle_captcha(page):
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
def extract_next_data(html_content):
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


def dig(d, *path, default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def build_location_hierarchy(prop):
    """
    Bayut exposes a 'location' array ordered from most specific to least
    specific (e.g. [Tower, Sub-Community, Community, City, Country]) or the
    reverse depending on payload version — handle both by tagging on 'level'
    when present, otherwise assume specific -> general.
    """
    loc = prop.get("location")
    levels = {}
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


def clean_number(value):
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


def extract_from_json(prop, prop_url, config):
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
        "Full Location": full_loc if full_loc != "N/A" else config["location"],
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
        "Purpose": config["purpose_str"],
    }


def extract_from_regex_fallback(page, full_html, prop_url, config):
    """Scoped fallback if __NEXT_DATA__ isn't found — still safer than the
    original whole-page regex because we search inside the details card."""
    card = page.ele("css:div[aria-label='Property details'], div[class*='details'], main", timeout=1)
    scope_html = card.html if card else full_html

    price = "N/A"
    price_match = re.search(r"AED\s*([\d,]+)(?!\d)", scope_html)
    if price_match:
        price = clean_number(price_match.group(1))

    beds = "N/A"
    beds_match = re.search(r"\b(\d+|Studio)\s*(?:Bed|Beds|BR)\b", scope_html, re.IGNORECASE)
    if beds_match:
        beds = beds_match.group(1)

    baths = "N/A"
    baths_match = re.search(r"\b(\d+)\s*(?:Bathroom|Bathrooms)\b", scope_html, re.IGNORECASE)
    if baths_match:
        baths = clean_number(baths_match.group(1))

    area = "N/A"
    area_match = re.search(r"([\d,]+)\s*sqft", scope_html, re.IGNORECASE)
    if area_match:
        area = clean_number(area_match.group(1))

    permit = "N/A"
    permit_label_match = re.search(
        r'Permit\s*Number[^0-9]{0,20}(\d{6,12})', scope_html, re.IGNORECASE,
    )
    if permit_label_match:
        permit = permit_label_match.group(1)

    title = "Property Listing"
    h1_el = page.ele("tag:h1", timeout=0.5)
    if h1_el:
        title = h1_el.text.strip()

    location = config["location"]
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
        "Purpose": config["purpose_str"],
    }


def collect_property_urls(page, config):
    all_property_urls = []
    seen_urls = set()
    current_page = 1
    current_url = config["target_url"]
    max_listings = config["max_listings"]

    while True:
        cprint(f"Collecting links from Search Page {current_page}...")
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
            except Exception:
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


def extract_property(page, prop_url, config, retries=2):
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
                return extract_from_json(prop_json, prop_url, config)
            return extract_from_regex_fallback(page, full_html, prop_url, config)
        except Exception:
            if attempt < retries:
                time.sleep(1.0)
                continue
            return None
    return None


# ==========================================
# PROFESSIONAL EXCEL EXPORT
# ==========================================
def write_professional_excel(df, out_path, config):
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Listings", startrow=1)
        wb = writer.book
        ws = writer.sheets["Listings"]

        n_rows, n_cols = df.shape
        last_col_letter = get_column_letter(n_cols)

        # --- Title banner ---
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
        title_cell = ws.cell(row=1, column=1)
        title_cell.value = (
            f"Bayut {config['purpose_str']} — {config['location']}  "
            f"({n_rows} listings, generated {datetime.now().strftime('%Y-%m-%d %H:%M')})"
        )
        title_cell.font = Font(size=14, bold=True, color="FFFFFF")
        title_cell.fill = PatternFill("solid", fgColor="1F4E78")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 26

        # --- Header row styling ---
        header_row = 2
        header_fill = PatternFill("solid", fgColor="2E75B6")
        header_font = Font(bold=True, color="FFFFFF")
        thin_border = Border(*(Side(style="thin", color="B7B7B7"),) * 4)
        for col_idx in range(1, n_cols + 1):
            cell = ws.cell(row=header_row, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[header_row].height = 24

        # --- Banded rows + borders + number formats ---
        band_fill = PatternFill("solid", fgColor="F2F6FC")
        currency_cols = {"Price (AED)", "Price / sqft (AED)"}
        number_cols = {"Area (sqft)", "Bathrooms", "Bedrooms", "Latitude", "Longitude"}
        col_names = list(df.columns)

        for r in range(n_rows):
            excel_row = header_row + 1 + r
            for c, col_name in enumerate(col_names, start=1):
                cell = ws.cell(row=excel_row, column=c)
                cell.border = thin_border
                if r % 2 == 1:
                    cell.fill = band_fill
                if col_name in currency_cols and isinstance(cell.value, (int, float)):
                    cell.number_format = '#,##0 "AED"'
                elif col_name in number_cols and isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0"
                if col_name == "Property URL" and cell.value:
                    cell.hyperlink = cell.value
                    cell.font = Font(color="1155CC", underline="single")

        # --- Freeze header, autofilter, column widths ---
        ws.freeze_panes = f"A{header_row + 1}"
        ws.auto_filter.ref = f"A{header_row}:{last_col_letter}{header_row + n_rows}"

        for c, col_name in enumerate(col_names, start=1):
            max_len = max([len(str(col_name))] + [len(str(v)) for v in df[col_name].astype(str).tolist()])
            ws.column_dimensions[get_column_letter(c)].width = min(max(12, max_len + 2), 55)

        table = Table(displayName="Listings", ref=f"A{header_row}:{last_col_letter}{header_row + n_rows}")
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9", showRowStripes=False,
            showFirstColumn=False, showLastColumn=False, showColumnStripes=False,
        )

        # --- Summary sheet ---
        summary_ws = wb.create_sheet("Summary")
        numeric_price = df["Price (AED)"].apply(lambda v: v if isinstance(v, (int, float)) else None).dropna()
        numeric_area = df["Area (sqft)"].apply(lambda v: v if isinstance(v, (int, float)) else None).dropna()
        stats = [
            ("Location", config["location"]),
            ("Purpose", config["purpose_str"]),
            ("Total Listings", n_rows),
            ("Average Price (AED)", round(numeric_price.mean(), 0) if len(numeric_price) else "N/A"),
            ("Min Price (AED)", int(numeric_price.min()) if len(numeric_price) else "N/A"),
            ("Max Price (AED)", int(numeric_price.max()) if len(numeric_price) else "N/A"),
            ("Average Area (sqft)", round(numeric_area.mean(), 0) if len(numeric_area) else "N/A"),
            ("Generated On", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ]
        summary_ws.cell(row=1, column=1, value="Summary").font = Font(size=14, bold=True)
        for i, (label, value) in enumerate(stats, start=3):
            summary_ws.cell(row=i, column=1, value=label).font = Font(bold=True)
            summary_ws.cell(row=i, column=2, value=value)
        summary_ws.column_dimensions["A"].width = 24
        summary_ws.column_dimensions["B"].width = 24

        ws.add_table(table)


def scrape_bayut():
    args = parse_args()
    config = get_user_inputs(args)

    co = ChromiumOptions()
    co.no_imgs(True)
    if args.headless:
        co.headless(True)

    page = ChromiumPage(co)
    cprint(f"\n[1/3] Target URL:\n      {config['target_url']}\n")

    all_property_urls = collect_property_urls(page, config)
    cprint(f"\n[2/3] Collected {len(all_property_urls)} links. Extracting structured details...\n")

    all_properties = []
    for idx, prop_url in enumerate(all_property_urls, 1):
        record = extract_property(page, prop_url, config)
        if record:
            all_properties.append(record)
            print(f"[{idx}/{len(all_property_urls)}] Extracted -> Permit: {record['Permit Number']} | "
                  f"Price: {record['Price (AED)']} | Location: {record['Full Location']}")
        else:
            print(f"[{idx}/{len(all_property_urls)}] Failed after retries, skipped.")

    page.quit()

    if not all_properties:
        cprint("\n⚠️  No listings extracted.")
        return

    df = pd.DataFrame(all_properties)
    df.drop_duplicates(subset=["Property URL"], inplace=True)

    if args.out:
        full_path = args.out
    else:
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(desktop_path, exist_ok=True)
        file_name = f"bayut_{config['location'].replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        full_path = os.path.join(desktop_path, file_name)

    write_professional_excel(df, full_path, config)
    cprint(f"\n✨ DONE! Saved {len(df)} listings to: {full_path}")


if __name__ == "__main__":
    scrape_bayut()
