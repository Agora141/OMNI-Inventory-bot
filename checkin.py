import csv
import logging
import os
import re

from config import DEFAULT_CONDITION, DEFAULT_UOM, LOCAL_CSV_PATH, SYSTEM_SHORT

logger = logging.getLogger(__name__)

_db_cache  = []
_db_by_nsn = {}
_db_by_mpn = {}


def load_database():
    global _db_cache, _db_by_nsn, _db_by_mpn

    import glob
    logger.info("CWD: %s", os.getcwd())
    logger.info("Files: %s", glob.glob("*"))
    logger.info("Looking for: %s", LOCAL_CSV_PATH)

    if not os.path.exists(LOCAL_CSV_PATH):
        logger.warning("parts_db not found: %s", LOCAL_CSV_PATH)
        return 0

    with open(LOCAL_CSV_PATH, newline="", encoding="utf-8") as f:
        _db_cache = list(csv.DictReader(f))

    _db_by_nsn = {r.get("nsn", "").upper(): r for r in _db_cache if r.get("nsn")}

    _db_by_mpn = {}
    for r in _db_cache:
        # part_number и mpn — одно и то же, поддерживаем оба
        mpn = (r.get("mpn") or r.get("part_number", "")).upper().strip()
        if mpn and mpn not in ("N/A", ""):
            _db_by_mpn[mpn] = r

    logger.info("loaded %d parts (%d NSN, %d MPN)", len(_db_cache), len(_db_by_nsn), len(_db_by_mpn))
    return len(_db_cache)


def search_part(query):
    if not _db_cache:
        load_database()

    q = query.strip().upper()
    digits = re.sub(r"\D", "", q)

    if len(digits) == 13:
        fmt = f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
        if fmt in _db_by_nsn:
            return _db_by_nsn[fmt]

    if q in _db_by_nsn:
        return _db_by_nsn[q]

    if q in _db_by_mpn:
        return _db_by_mpn[q]

    if len(q) >= 4:
        hits = [r for mpn, r in _db_by_mpn.items() if q in mpn or mpn in q]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return sorted(hits, key=lambda r: len(r.get("mpn", r.get("part_number", ""))))[0]

    if len(q) >= 5:
        hits = [r for r in _db_cache if q in r.get("name", r.get("part_name", "")).upper()]
        if hits:
            return hits[0]

    return None


def search_multiple(query, limit=5):
    if not _db_cache:
        load_database()

    q = query.strip().upper()
    results = []

    for mpn, r in _db_by_mpn.items():
        if q in mpn:
            results.append(r)
        if len(results) >= limit:
            break

    if len(results) < limit:
        for r in _db_cache:
            name = r.get("name", r.get("part_name", "")).upper()
            if q in name and r not in results:
                results.append(r)
            if len(results) >= limit:
                break

    return results[:limit]


def update_part_in_db(inventory_id, quantity, storage_location, condition, photo_url=""):
    if not _db_cache:
        load_database()

    updated = False
    for r in _db_cache:
        if r.get("inventory_id", "") == inventory_id:
            r["quantity"] = str(quantity)
            r["storage_location"] = storage_location
            r["condition"] = condition
            if photo_url:
                r["photo_url"] = photo_url
            updated = True
            break

    if not updated:
        return False

    fieldnames = list(_db_cache[0].keys())
    for col in ("photo_url", "storage_location", "quantity", "condition"):
        if col not in fieldnames:
            fieldnames.append(col)

    with open(LOCAL_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in _db_cache:
            for k in fieldnames:
                row.setdefault(k, "")
            writer.writerow(row)

    return True


def format_part_card(r):
    price = float(r.get("unit_price", 0) or 0)
    qty   = r.get("quantity", "0") or "0"
    loc   = r.get("storage_location", "") or "не задана"
    mpn   = r.get("part_number", r.get("mpn", "N/A"))
    name  = r.get("name", r.get("part_name", "Неизвестно"))
    cat   = r.get("category", r.get("category_section", ""))

    return (
        f"📦 <b>{name[:60]}</b>\n\n"
        f"🔢 <b>NSN:</b> <code>{r.get('nsn', 'N/A')}</code>\n"
        f"🏷 <b>MPN:</b> <code>{mpn}</code>\n"
        f"🏭 <b>CAGE:</b> {r.get('cage_code', '—')}\n"
        f"📂 <b>Категория:</b> {cat}\n"
        f"📍 <b>ID:</b> {r.get('inventory_id', '—')}\n"
        f"💰 <b>Цена:</b> {'${:.2f}'.format(price) if price else '—'}\n"
        f"📊 <b>Склад:</b> {qty} {r.get('unit', DEFAULT_UOM)} | {loc}\n"
        f"🔧 <b>Состояние:</b> {r.get('condition', DEFAULT_CONDITION)}"
    )


def get_stats():
    if not _db_cache:
        load_database()

    total       = len(_db_cache)
    inventoried = sum(1 for r in _db_cache if int(r.get("quantity", "0") or 0) > 0)
    located     = sum(1 for r in _db_cache
                      if r.get("storage_location", "").strip() not in ("", "UNASSIGNED"))
    with_photo  = sum(1 for r in _db_cache if r.get("photo_url", "").strip())

    return {
        "total":        total,
        "inventoried":  inventoried,
        "located":      located,
        "with_photo":   with_photo,
        "remaining":    total - inventoried,
        "progress_pct": round(inventoried / total * 100, 1) if total else 0,
    }
