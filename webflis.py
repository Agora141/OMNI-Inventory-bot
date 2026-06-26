import logging
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TIMEOUT = 10
_cache   = {}


def get_unit_price(nsn):
    nsn = nsn.strip().upper()
    if nsn in _cache:
        return _cache[nsn]

    price = _from_nsncenter(nsn) or _from_webflis(nsn.replace("-", "")) or 0.0
    _cache[nsn] = price
    return price


def _from_nsncenter(nsn):
    try:
        resp = requests.get(
            f"https://www.nsncenter.com/NSN/{nsn}",
            headers=_HEADERS, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            return None

        text  = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)
        match = re.search(r"(?:Unit\s*Price|Price)[:\s]+\$?([\d,]+\.?\d*)", text, re.I)
        if match:
            return float(match.group(1).replace(",", ""))
    except Exception as e:
        logger.debug("nsncenter error for %s: %s", nsn, e)

    return None


def _from_webflis(nsn_digits):
    if len(nsn_digits) < 9:
        return None

    niin = nsn_digits[-9:]
    try:
        resp = requests.post(
            "https://www.dlis.dla.mil/WebFLIS/AdvisoryDataServlet",
            data={"reqtype": "NIIN", "niin": niin, "format": "json"},
            headers=_HEADERS, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            return None

        data = resp.json()
        for key in ("unitPrice", "unit_price", "UNIT_PRICE", "price"):
            if key in data:
                try:
                    return float(str(data[key]).replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        logger.debug("webflis error for %s: %s", niin, e)

    return None


def get_part_details(nsn):
    nsn = nsn.strip().upper()
    result = {"nsn": nsn, "name": "", "category": "", "unit_price": 0.0, "unit": "EA"}

    try:
        resp = requests.get(
            f"https://www.nsncenter.com/NSN/{nsn}",
            headers=_HEADERS, timeout=_TIMEOUT
        )
        if resp.status_code != 200:
            return result

        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)

        m = re.search(r"Item\s*Name[:\s]+([A-Z][A-Z0-9 ,\-/]{3,60})", text, re.I)
        if m:
            result["name"] = m.group(1).strip()

        m = re.search(r"Unit\s*of\s*Issue[:\s]+([A-Z]{2})", text, re.I)
        if m:
            result["unit"] = m.group(1)

        m = re.search(r"Unit\s*Price[:\s]+\$?([\d,]+\.?\d*)", text, re.I)
        if m:
            result["unit_price"] = float(m.group(1).replace(",", ""))
    except Exception as e:
        logger.debug("get_part_details error for %s: %s", nsn, e)

    return result
