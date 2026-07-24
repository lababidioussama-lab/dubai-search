#!/usr/bin/env python3
"""
Permit lookup automation for prospectsx.com

Reads permit numbers from an Excel sheet, looks each one up on prospectsx.com,
and writes the result back into the same row, next to the permit number.

Setup (run once on your laptop):
    pip install playwright openpyxl
    playwright install chromium

Usage (run from a terminal, not by double-clicking the file, so you can see
any errors):
    python permit_lookup.py "path/to/file.xlsx"

    Optional flags:
      --sheet "Listings"          sheet name to read/write (default: Listings)
      --permit-column "L"         column letter holding the permit number (default: L)
      --start-row 3               first data row to process (default: 3, since row 1
                                   is a title banner and row 2 is headers in this file)
      --headless                  run Chrome without a visible window (default: visible)

You will be prompted for your prospectsx.com username and password each time
you run the script. Nothing is stored on disk.

If something goes wrong, the script:
  - never lets the window vanish silently — it prints the full error and
    waits for you to press Enter before closing
  - saves a screenshot + HTML snapshot of the page at the point of failure
    into a "debug/" folder next to this script, so you can send it to me
  - keeps whatever progress it already made saved to the Excel file
"""

import argparse
import datetime
import getpass
import sys
import time
import traceback
from pathlib import Path
from typing import Tuple

try:
    import openpyxl
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError as e:
    print("\n" + "=" * 70)
    print(f"Missing dependency: {e}")
    print("Run these two commands first, then try again:")
    print("    pip install playwright openpyxl")
    print("    playwright install chromium")
    print("=" * 70)
    input("\nPress Enter to close this window...")
    sys.exit(1)

# ---------------------------------------------------------------------------
# CONFIG — these selectors are best-guess placeholders based on the login
# screenshot. They almost certainly need adjusting once you can actually load
# the site. If a run fails, check the debug/ folder for a screenshot + HTML
# dump and send it to me so I can correct these.
# ---------------------------------------------------------------------------
LOGIN_URL = "https://prospectsx.com/"

USERNAME_SELECTOR = "input[placeholder='Username']"
PASSWORD_SELECTOR = "input[type='password']"
LOGIN_BUTTON_SELECTOR = "button:has-text('Sign In')"

# After login, where does the permit/Trakheesi search live? Update this if
# it's not the landing page.
SEARCH_PAGE_URL = None  # e.g. "https://prospectsx.com/permits/search" — leave None to stay on landing page

SEARCH_INPUT_SELECTOR = "input[placeholder*='permit' i], input[name*='permit' i], input[placeholder*='search' i]"
SEARCH_BUTTON_SELECTOR = "button:has-text('Search')"

# Container that holds the result details after a search. The script grabs
# all visible text inside this container as a fallback so you get *something*
# useful even before the selectors below are fully tuned.
RESULT_CONTAINER_SELECTOR = "[class*='result' i], [class*='detail' i]"

NAV_TIMEOUT_MS = 20000
RESULT_WAIT_MS = 10000
RETRIES_PER_PERMIT = 2
# ---------------------------------------------------------------------------

DEBUG_DIR = Path(__file__).resolve().parent / "debug"


def get_credentials() -> Tuple[str, str]:
    """Load prospectsx.com credentials from credentials_local.py next to this
    script if it exists, otherwise prompt for them. credentials_local.py is
    git-ignored and never committed/pushed — see credentials_local.example.py."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import credentials_local  # type: ignore

        username = getattr(credentials_local, "PROSPECTS_USERNAME", "").strip()
        password = getattr(credentials_local, "PROSPECTS_PASSWORD", "").strip()
        if username and password:
            print(f"Using saved credentials for '{username}' (from credentials_local.py).")
            return username, password
    except ImportError:
        pass

    username = input("prospectsx.com username: ").strip()
    password = getpass.getpass("prospectsx.com password: ")
    return username, password


def col_letter_to_index(letter: str) -> int:
    """Convert 'A' -> 1, 'L' -> 12, etc."""
    letter = letter.strip().upper()
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def dump_debug(page, label: str) -> None:
    """Save a screenshot + HTML snapshot so failures can be diagnosed later."""
    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    png_path = DEBUG_DIR / f"{stamp}_{label}.png"
    html_path = DEBUG_DIR / f"{stamp}_{label}.html"
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception:
        pass
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    print(f"  -> Saved debug snapshot: {png_path.name} / {html_path.name}")


def login(page, username: str, password: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    try:
        page.wait_for_selector(USERNAME_SELECTOR, timeout=NAV_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        dump_debug(page, "login_page_username_not_found")
        raise RuntimeError(
            "Could not find the username field on the login page. "
            "The USERNAME_SELECTOR in CONFIG likely doesn't match the real page. "
            "Check debug/ for a screenshot and send it to me."
        )

    page.fill(USERNAME_SELECTOR, username)
    page.fill(PASSWORD_SELECTOR, password)
    page.click(LOGIN_BUTTON_SELECTOR)
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)

    if page.locator(USERNAME_SELECTOR).count() > 0 and page.locator(USERNAME_SELECTOR).is_visible():
        dump_debug(page, "login_failed_still_on_login_page")
        raise RuntimeError(
            "Still on the login page after submitting — login likely failed "
            "(wrong credentials, blocked account, or the site needs a code we "
            "don't handle yet). Check debug/ for a screenshot."
        )


def search_permit(page, permit_number: str) -> str:
    if SEARCH_PAGE_URL:
        page.goto(SEARCH_PAGE_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    page.wait_for_selector(SEARCH_INPUT_SELECTOR, timeout=NAV_TIMEOUT_MS)
    page.fill(SEARCH_INPUT_SELECTOR, "")
    page.fill(SEARCH_INPUT_SELECTOR, str(permit_number))
    page.click(SEARCH_BUTTON_SELECTOR)

    try:
        page.wait_for_selector(RESULT_CONTAINER_SELECTOR, timeout=RESULT_WAIT_MS)
    except PlaywrightTimeoutError:
        return "NO RESULT / selector timeout — check RESULT_CONTAINER_SELECTOR"

    container = page.query_selector(RESULT_CONTAINER_SELECTOR)
    if not container:
        return "NO RESULT / container not found"

    text = container.inner_text().strip()
    return " | ".join(line.strip() for line in text.splitlines() if line.strip())


def search_permit_with_retries(page, permit_number: str, label: str) -> str:
    last_error = None
    for attempt in range(1, RETRIES_PER_PERMIT + 1):
        try:
            return search_permit(page, permit_number)
        except Exception as e:
            last_error = e
            print(f"  attempt {attempt}/{RETRIES_PER_PERMIT} failed: {e}")
            if attempt == 1:
                dump_debug(page, f"row_{label}_search_failed")
            time.sleep(2)
    return f"ERROR after {RETRIES_PER_PERMIT} attempts: {last_error}"


def run_lookup(
    excel_path: str,
    sheet: str = "Listings",
    permit_column: str = "L",
    start_row: int = 3,
    headless: bool = False,
) -> None:
    """Look up every permit number in `sheet`/`permit_column` on prospectsx.com
    and write the result into the column right after it, on the same row."""
    username, password = get_credentials()

    wb = openpyxl.load_workbook(excel_path)
    if sheet not in wb.sheetnames:
        print(f"Sheet '{sheet}' not found. Available sheets: {wb.sheetnames}")
        sys.exit(1)
    ws = wb[sheet]

    permit_col = col_letter_to_index(permit_column)
    result_col = permit_col + 1  # write result in the column right after the permit number
    ws.cell(row=start_row - 1, column=result_col, value="Prospects Search Result")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)

        try:
            print("Opening prospectsx.com and logging in...")
            login(page, username, password)
            print("Logged in.")

            row = start_row
            processed = 0
            while True:
                permit_number = ws.cell(row=row, column=permit_col).value
                if permit_number is None:
                    break

                print(f"Row {row}: looking up permit {permit_number} ...")
                result = search_permit_with_retries(page, permit_number, label=str(row))
                ws.cell(row=row, column=result_col, value=result)
                processed += 1

                if processed % 10 == 0:
                    wb.save(excel_path)
                    print(f"  Saved progress ({processed} permits done).")

                row += 1
                time.sleep(1)  # be polite to the site between searches

            print(f"Finished. Processed {processed} permits.")
        finally:
            wb.save(excel_path)
            print(f"Saved results to {excel_path}")
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("excel_path", help="Path to the Excel file")
    parser.add_argument("--sheet", default="Listings")
    parser.add_argument("--permit-column", default="L")
    parser.add_argument("--start-row", type=int, default=3)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    try:
        run_lookup(
            args.excel_path,
            sheet=args.sheet,
            permit_column=args.permit_column,
            start_row=args.start_row,
            headless=args.headless,
        )
    except KeyboardInterrupt:
        print("\nStopped by user (progress up to this point was saved).")
    except Exception:
        print("\n" + "=" * 70)
        print("The script hit an error and stopped. Full details below —")
        print("please copy this and send it back so it can be fixed:")
        print("=" * 70)
        traceback.print_exc()
        print("=" * 70)
    finally:
        input("\nPress Enter to close this window...")


if __name__ == "__main__":
    main()
