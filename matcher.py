import csv
import logging
import os
import re

import requests

from config import LOCAL_CSV_PATH

logger = logging.getLogger(__name__)

NSN_PATTERN       = re.compile(r"\b(\d{4})[- ]?(\d{2})[- ]?(\d{3})[- ]?(\d{4})\b")
NSN_PLAIN_PATTERN = re.compile(r"\b(\d{13})\b")
PART_NUMBER_PATTERN = re.compile(
    r"\b([A-Z]{1,4}[-]?[0-9]{4,}[A-Z0-9\-]*|[0-9]{4,}[A-Z][A-Z0-9\-]*)\b"
)

_NSNCENTER_URL = "https://www.nsncenter.com/NSN/{nsn}"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TIMEOUT = 8


def normalize_nsn(raw):
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 13:
        return f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
    return raw


def extract_candidates(text):
    text_upper = text.upper()
    nsns = []

    for m in NSN_PATTERN.finditer(text_upper):
        nsn = f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
        nsns.append(nsn)

    for m in NSN_PLAIN_PATTERN.finditer(text_upper):
        nsn = normalize_nsn(m.group(1))
        if nsn not in nsns:
            nsns.append(nsn)

    part_numbers = []
    for m in PART_NUMBER_PATTERN.finditer(text_upper):
        pn = m.group(1)
        if pn not in part_numbers:
            part_numbers.append(pn)

    return {"nsns": nsns, "part_numbers": part_numbers}


def search_local_csv(nsns, part_numbers):
    if not os.path.exists(LOCAL_CSV_PATH):
        return None

    try:
        with open(LOCAL_CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row_nsn = row.get("nsn", "").strip().upper()
                row_pn  = row.get("part_number", "").strip().upper()

                if row_nsn in nsns:
                    return _make_result(row, "local_csv")
                if row_pn and row_pn in part_numbers:
                    return _make_result(row, "local_csv")
    except Exception as e:
        logger.error("csv read error: %s", e)

    return None


def _make_result(row, source):
    return {
        "nsn":         row.get("nsn", "N/A").strip(),
        "part_number": row.get("part_number", "N/A").strip(),
        "name":        row.get("name", "Unknown").strip(),
        "category":    row.get("category", "").strip(),
        "source":      source,
    }


def search_http(nsns):
    for nsn in nsns:
        url = _NSNCENTER_URL.format(nsn=nsn)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code != 200:
                continue

            html = resp.text

            name_m = re.search(r'Item Name[:\s<>/\w"=]+?>([A-Z0-9 ,\-/]+)<', html)
            name   = name_m.group(1).strip() if name_m else "Unknown"

            fsc_m    = re.search(r'FSC[:\s<>/\w"=]+?>(\d{4}[^<]+)<', html)
            category = fsc_m.group(1).strip() if fsc_m else ""

            pn_m    = re.search(r'Part Number[:\s<>/\w"=]+?>([A-Z0-9\-]+)<', html)
            part_no = pn_m.group(1).strip() if pn_m else "N/A"

            if name != "Unknown":
                return {
                    "nsn":         nsn,
                    "part_number": part_no,
                    "name":        name,
                    "category":    category,
                    "source":      "nsncenter.com",
                }
        except requests.RequestException as e:
            logger.warning("http error for %s: %s", nsn, e)

    return None


def find_part(ocr_text):
    candidates    = extract_candidates(ocr_text)
    nsns          = candidates["nsns"]
    part_numbers  = candidates["part_numbers"]

    if not nsns and not part_numbers:
        return None

    result = search_local_csv(nsns, part_numbers)
    if result:
        return result

    if nsns:
        result = search_http(nsns)
        if result:
            return result

    if nsns or part_numbers:
        return {
            "nsn":         nsns[0] if nsns else "N/A",
            "part_number": part_numbers[0] if part_numbers else "N/A",
            "name":        "Not identified",
            "category":    "",
            "source":      "ocr_only",
        }

    return None
