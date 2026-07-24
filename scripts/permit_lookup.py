#!/usr/bin/env python3
"""
Permit lookup automation for prospectsx.com

Reads permit numbers from an Excel sheet, looks each one up on prospectsx.com,
and writes the result back into the same row, next to the permit number.

Setup (run once on your laptop):
    pip install playwright openpyxl
    playwright install chromium

Usage:
    python permit_lookup.py "path/to/file.xlsx"

    Optional flags:
      --sheet "Listings"          sheet name to read/write (default: Listings)
      --permit-column "L"         column letter holding the permit number (default: L)
      --start-row 3               first data row to process (default: 3, since row 1
                                   is a title banner and row 2 is headers in this file)
      --headless                  run Chrome without a visible window (default: visible)

You will be prompted for your prospectsx.com username and password each time
you run the script. Nothing is stored on disk.
"""

import argparse
import getpass
import sys
import time

import openpyxl
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------------------------------------------------------------------------
# CONFIG — these selectors are best-guess placeholders based on the login
# screenshot. They almost certainly need adjusting once you can actually load
# the site. See the "How to find the real selectors" section in the README
# note printed below, or just run once with --headless off, watch where it
# fails, and send me what you see (or the page HTML) so I can fix the
# selectors for you.
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

RESULT_WAIT_MS = 8000
# ---------------------------------------------------------------------------


def col_letter_to_index(letter: str) -> int:
    """Convert 'A' -> 1, 'L' -> 12, etc."""
    letter = letter.strip().upper()
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def login(page, username: str, password: str) -> None:
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill(USERNAME_SELECTOR, username)
    page.fill(PASSWORD_SELECTOR, password)
    page.click(LOGIN_BUTTON_SELECTOR)
    page.wait_for_load_state("networkidle")


def search_permit(page, permit_number: str) -> str:
    if SEARCH_PAGE_URL:
        page.goto(SEARCH_PAGE_URL, wait_until="domcontentloaded")

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("excel_path", help="Path to the Excel file")
    parser.add_argument("--sheet", default="Listings")
    parser.add_argument("--permit-column", default="L")
    parser.add_argument("--start-row", type=int, default=3)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    username = input("prospectsx.com username: ").strip()
    password = getpass.getpass("prospectsx.com password: ")

    wb = openpyxl.load_workbook(args.excel_path)
    if args.sheet not in wb.sheetnames:
        print(f"Sheet '{args.sheet}' not found. Available sheets: {wb.sheetnames}")
        sys.exit(1)
    ws = wb[args.sheet]

    permit_col = col_letter_to_index(args.permit_column)
    result_col = permit_col + 1  # write result in the column right after the permit number
    ws.cell(row=args.start_row - 1, column=result_col, value="Prospects Search Result")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        page = browser.new_page()

        print("Logging in...")
        login(page, username, password)

        row = args.start_row
        processed = 0
        while True:
            permit_number = ws.cell(row=row, column=permit_col).value
            if permit_number is None:
                break

            print(f"Row {row}: looking up permit {permit_number} ...")
            try:
                result = search_permit(page, permit_number)
            except Exception as e:
                result = f"ERROR: {e}"

            ws.cell(row=row, column=result_col, value=result)
            processed += 1

            if processed % 10 == 0:
                wb.save(args.excel_path)
                print(f"Saved progress ({processed} permits done).")

            row += 1
            time.sleep(1)  # be polite to the site between searches

        browser.close()

    wb.save(args.excel_path)
    print(f"Done. Processed {processed} permits. Saved to {args.excel_path}")


if __name__ == "__main__":
    main()
