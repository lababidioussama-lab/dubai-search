#!/usr/bin/env python3
"""
Oussama's Dubai Real Estate Toolkit — unified launcher.

Two tools in one place:
  1. Bayut Scraper           — pull fresh listings from Bayut into a
                                formatted Excel report (bayut_scraper.py)
  2. Prospects Permit Lookup — take permit numbers from an existing Excel
                                file and look each one up on prospectsx.com
                                (permit_lookup.py)

Run:
    python main.py
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GREEN = "\033[92m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner() -> None:
    print(f"{GREEN}{BOLD}")
    print("=" * 70)
    print("            OUSSAMA'S DUBAI REAL ESTATE TOOLKIT")
    print("=" * 70)
    print(RESET)


def choose_mode() -> str:
    print("What do you want to do?\n")
    print("  1. Scrape Bayut listings          (build a new Excel report)")
    print("  2. Permit Lookup on Prospects      (enrich an existing Excel file)")
    while True:
        choice = input(f"\n{GREEN}Choice (1 or 2): {RESET}").strip()
        if choice in ("1", "2"):
            return choice
        print("Please enter 1 or 2.")


def run_scrape() -> None:
    from bayut_scraper import scrape_bayut

    scrape_bayut()


def run_lookup_flow() -> None:
    from permit_lookup import run_lookup

    print()
    excel_path = input(f"{GREEN}Path to the Excel file with permit numbers: {RESET}").strip().strip('"')
    if not Path(excel_path).exists():
        print(f"File not found: {excel_path}")
        return

    sheet = input(f"{GREEN}Sheet name (press ENTER for 'Listings'): {RESET}").strip() or "Listings"
    permit_column = input(f"{GREEN}Column letter with permit numbers (press ENTER for 'L'): {RESET}").strip() or "L"

    run_lookup(excel_path, sheet=sheet, permit_column=permit_column)


def main() -> None:
    print_banner()
    choice = choose_mode()

    try:
        if choice == "1":
            run_scrape()
        else:
            run_lookup_flow()
    except KeyboardInterrupt:
        print("\nStopped by user.")
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
