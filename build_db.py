"""
build_db.py — Utility script to extend parts_db.csv from external sources.

Run manually (not by the bot) when you need to update the database.

Sources (in priority order):
  1. nsncenter.com  — search by FSC codes
  2. Local PDF manuals if downloaded (e.g. TM 9-2320-280-24P)

Usage:
  # Update existing database with new records:
  python build_db.py

  # Parse a PDF manual:
  python build_db.py --pdf /path/to/TM-9-2320-280-24P-1.pdf

Dependencies:
  pip install requests beautifulsoup4 pdfplumber

Free manual downloads:
  https://archive.org/details/131-hmmwv-manuals
  Files: TM 9-2320-280-24P-1 (Vol 1) and TM 9-2320-280-24P-2 (Vol 2)
"""

import csv
import re
import sys
import time
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CSV_PATH = Path("parts_db.csv")

# FSC codes for common equipment parts
HMMWV_FSC_CODES = [
    "2510",  # Body / Hull
    "2520",  # Transmission and drive
    "2530",  # Brakes, wheels, steering
    "2590",  # Suspension and misc automotive
    "2815",  # Engine
    "2910",  # Fuel system
    "3010",  # Drive shafts
    "4330",  # Cooling
    "4520",  # Heating
    "6150",  # Electrical
    "6220",  # Lighting
    "1005",  # Armament mounts
]


def load_existing_csv() -> dict:
    """Load existing CSV, return dict {nsn: row}."""
    existing = {}
    if not CSV_PATH.exists():
        return existing
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nsn = row.get("nsn", "").strip()
            if nsn:
                existing[nsn] = row
    logger.info("loaded %d records from CSV", len(existing))
    return existing


def save_csv(records: dict):
    """Save records dict to CSV."""
    fieldnames = ["nsn", "part_number", "name", "category", "unit", "unit_price"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records.values():
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    logger.info("saved %d records to CSV", len(records))


def scrape_nsncenter(fsc: str, existing_nsns: set) -> list:
    """
    Scrape nsncenter.com by FSC code.
    Returns list of new records.

    NOTE: Run only from a real machine with internet access.
    """
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    new_records = []
    page = 1

    while True:
        url = f"https://www.nsncenter.com/Category/{fsc}?page={page}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                break

            soup = BeautifulSoup(r.text, "html.parser")

            # Look for rows containing NSN
            rows = soup.find_all("tr")
            found_on_page = 0

            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue

                text = row.get_text(" ", strip=True)
                nsn_match = re.search(r"(\d{4}-\d{2}-\d{3}-\d{4})", text)
                if not nsn_match:
                    continue

                nsn = nsn_match.group(1)
                if nsn in existing_nsns:
                    continue

                # Try to extract part name
                name = cells[1].get_text(strip=True) if len(cells) > 1 else "Unknown"
                price_match = re.search(r"\$?([\d,]+\.?\d*)", text)
                price = float(price_match.group(1).replace(",", "")) if price_match else 0.0

                new_records.append({
                    "nsn":         nsn,
                    "part_number": "N/A",
                    "name":        name,
                    "category":    _fsc_to_category(fsc),
                    "unit":        "EA",
                    "unit_price":  price,
                })
                existing_nsns.add(nsn)
                found_on_page += 1

            if found_on_page == 0:
                break  # Empty page — end of results

            page += 1
            time.sleep(1)  # Polite delay

        except Exception as e:
            logger.error("scraping error FSC %s page %d: %s", fsc, page, e)
            break

    return new_records


def parse_pdf_manual(pdf_path: str) -> list:
    """
    Parse a PDF parts manual and extract NSN numbers.

    Free downloads:
    https://archive.org/details/131-hmmwv-manuals

    Manual structure:
    - Each part has a line: NSN | Part Name | Qty | Part Number
    - NSN in format 4-2-3-4 or without dashes
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("Install pdfplumber: pip install pdfplumber")
        return []

    records = []
    seen_nsns = set()

    logger.info("parsing PDF: %s", pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        logger.info("total pages: %d", total)

        for i, page in enumerate(pdf.pages):
            if i % 50 == 0:
                logger.info("processed pages: %d / %d", i, total)

            text = page.extract_text() or ""

            # Search for NSN patterns like: 2530-01-109-1022
            nsn_pattern = re.compile(r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b")

            for match in nsn_pattern.finditer(text):
                nsn = match.group(1)
                if nsn in seen_nsns:
                    continue

                # Get context after NSN (150 chars)
                start = match.end()
                context = text[start:start + 150].strip()

                # Normalize whitespace
                context = re.sub(r"\s+", " ", context)

                # Try to extract part name — usually follows the NSN
                name_match = re.match(
                    r"([A-Z][A-Z0-9 ,\-/\.]{5,60}?)(?:\s{2,}|\d+\s+[A-Z0-9\-]{4,})",
                    context,
                )
                name = name_match.group(1).strip() if name_match else "See Manual"

                # Part number — alphanumeric code
                pn_match = re.search(r"\b([A-Z0-9]{2,}-[A-Z0-9]{2,}|[0-9]{5,}[A-Z]?)\b", context)
                part_number = pn_match.group(1) if pn_match else "N/A"

                # Determine category from FSC (first 4 digits of NSN)
                fsc = nsn[:4]
                category = _fsc_to_category(fsc)

                records.append({
                    "nsn":         nsn,
                    "part_number": part_number,
                    "name":        name[:80],
                    "category":    category,
                    "unit":        "EA",
                    "unit_price":  0.0,  # no price in manual — use WEBFLIS
                })
                seen_nsns.add(nsn)

    logger.info("found %d unique NSNs in PDF", len(records))
    return records


def _fsc_to_category(fsc: str) -> str:
    """Convert FSC code to readable category name."""
    mapping = {
        "2510": "Body / Armor",
        "2520": "Drivetrain",
        "2530": "Brakes / Wheels",
        "2590": "Suspension",
        "2815": "Engine",
        "2910": "Engine / Fuel",
        "3010": "Drivetrain",
        "4330": "Heating / Cooling",
        "4520": "Heating / Cooling",
        "6150": "Electrical",
        "6220": "Electrical",
        "1005": "Armament",
        "5820": "Electrical",
        "9340": "Body / Armor",
    }
    return mapping.get(fsc, f"FSC-{fsc}")


def main():
    parser = argparse.ArgumentParser(description="Update parts database from external sources")
    parser.add_argument("--pdf",  help="Path to PDF parts manual")
    parser.add_argument("--scrape", action="store_true",
                        help="Scrape nsncenter.com (requires internet)")
    parser.add_argument("--stats", action="store_true",
                        help="Show current database stats")
    args = parser.parse_args()

    existing = load_existing_csv()

    if args.stats or (not args.pdf and not args.scrape):
        # Show database stats
        print(f"\n{'='*50}")
        print(f"Database: {CSV_PATH}")
        print(f"{'='*50}")
        print(f"Total records: {len(existing)}")

        categories = {}
        for row in existing.values():
            cat = row.get("category", "Unknown")
            categories[cat] = categories.get(cat, 0) + 1

        print("\nBy category:")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} parts")

        total_value = sum(
            float(r.get("unit_price", 0) or 0) for r in existing.values()
        )
        print(f"\nTotal catalog value: ${total_value:,.2f}")
        print(f"{'='*50}\n")

        if not args.pdf and not args.scrape:
            print("Usage:")
            print("  python build_db.py --stats           # show stats")
            print("  python build_db.py --pdf manual.pdf  # parse PDF manual")
            print("  python build_db.py --scrape          # scrape website (needs internet)")
            print()
            print("Free manual downloads:")
            print("  https://archive.org/details/131-hmmwv-manuals")
            print("  File: TM 9-2320-280-24P-1 (Vol 1, ~450 MB)")
            print("  File: TM 9-2320-280-24P-2 (Vol 2, ~430 MB)")
        return

    new_records = []
    existing_nsns = set(existing.keys())

    if args.pdf:
        pdf_records = parse_pdf_manual(args.pdf)
        new_records.extend(pdf_records)
        logger.info("new records from PDF: %d", len(pdf_records))

    if args.scrape:
        for fsc in HMMWV_FSC_CODES:
            logger.info("scraping FSC %s...", fsc)
            fsc_records = scrape_nsncenter(fsc, existing_nsns)
            new_records.extend(fsc_records)
            logger.info("FSC %s: %d new records", fsc, len(fsc_records))
            time.sleep(2)

    if new_records:
        for rec in new_records:
            nsn = rec["nsn"]
            if nsn not in existing:
                existing[nsn] = rec

        save_csv(existing)
        logger.info("added %d new records. Total in database: %d", len(new_records), len(existing))
    else:
        logger.info("no new records found.")


if __name__ == "__main__":
    main()
