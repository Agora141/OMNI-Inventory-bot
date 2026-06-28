import logging
import re
import time

from config import DEFAULT_CONDITION, DEFAULT_UOM, SUPABASE_URL, SUPABASE_SECRET_KEY, SYSTEM_SHORT

logger = logging.getLogger(__name__)

# In-memory cache — loaded once at startup
_cache_by_nsn = {}
_cache_by_mpn = {}
_cache_all    = []
_cache_loaded = False

_supabase = None

def _get_db():
    global _supabase
    if _supabase:
        return _supabase
    from supabase import create_client
    _supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    return _supabase


def load_database():
    """Load all inventory into memory at startup. Search will be instant."""
    global _cache_by_nsn, _cache_by_mpn, _cache_all, _cache_loaded

    try:
        db = _get_db()
        t0 = time.time()

        # Load all rows — done once, stays in RAM
        res = db.table("inventory").select(
            "id,inventory_id,nsn,mpn,cage_code,part_name,category_section,"
            "quantity,uom,storage_location,unit_price,total_value,condition,photo_url"
        ).execute()

        rows = res.data or []
        _cache_all = rows

        _cache_by_nsn = {}
        _cache_by_mpn = {}

        for r in rows:
            nsn = (r.get("nsn") or "").strip().upper()
            mpn = (r.get("mpn") or "").strip().upper()
            if nsn:
                _cache_by_nsn[nsn] = r
            if mpn and mpn not in ("N/A", ""):
                _cache_by_mpn[mpn] = r

        _cache_loaded = True
        logger.info("cache loaded: %d parts in %.2fs", len(rows), time.time() - t0)
        return len(rows)

    except Exception as e:
        logger.error("load_database error: %s", e)
        return 0


def _ensure_loaded():
    if not _cache_loaded:
        load_database()


def search_part(query):
    if not query or not query.strip():
        return None

    _ensure_loaded()
    q = query.strip().upper()
    digits = re.sub(r"\D", "", q)

    # Try NSN 13-digit format
    if len(digits) == 13:
        nsn = f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
        if nsn in _cache_by_nsn:
            return _cache_by_nsn[nsn]

    # Exact NSN
    if q in _cache_by_nsn:
        return _cache_by_nsn[q]

    # Exact MPN
    if q in _cache_by_mpn:
        return _cache_by_mpn[q]

    # Partial MPN
    hits = [r for mpn, r in _cache_by_mpn.items() if q in mpn]
    if hits:
        return hits[0]

    # Part name
    hits = [r for r in _cache_all if q in (r.get("part_name") or "").upper()]
    if hits:
        return hits[0]

    return None


def search_multiple(query, limit=5):
    if not query or not query.strip():
        return []

    _ensure_loaded()
    q = query.strip().upper()
    results = []
    seen = set()

    for mpn, r in _cache_by_mpn.items():
        if q in mpn and r["id"] not in seen:
            results.append(r)
            seen.add(r["id"])
        if len(results) >= limit:
            break

    if len(results) < limit:
        for r in _cache_all:
            if q in (r.get("part_name") or "").upper() and r["id"] not in seen:
                results.append(r)
                seen.add(r["id"])
            if len(results) >= limit:
                break

    return results[:limit]


def update_part_in_db(inventory_id, quantity, storage_location, condition, photo_url=""):
    try:
        db = _get_db()
        update = {
            "quantity":         quantity,
            "storage_location": storage_location,
            "condition":        condition,
        }
        if photo_url:
            update["photo_url"] = photo_url
        db.table("inventory").update(update).eq("inventory_id", inventory_id).execute()

        # Update cache
        for r in _cache_all:
            if r.get("inventory_id") == inventory_id:
                r.update(update)
                break
        return True
    except Exception as e:
        logger.error("update_part_in_db error: %s", e)
        return False


def format_part_card(r):
    price = float(r.get("unit_price") or 0)
    qty   = r.get("quantity") or 0
    loc   = r.get("storage_location") or "not set"
    mpn   = r.get("mpn") or "N/A"
    name  = r.get("part_name") or "Unknown"
    cat   = r.get("category_section") or ""

    return (
        f"📦 <b>{name[:60]}</b>\n\n"
        f"🔢 <b>NSN:</b> <code>{r.get('nsn') or 'N/A'}</code>\n"
        f"🏷 <b>MPN:</b> <code>{mpn}</code>\n"
        f"🏭 <b>CAGE:</b> {r.get('cage_code') or '—'}\n"
        f"📂 <b>Category:</b> {cat}\n"
        f"📍 <b>ID:</b> {r.get('inventory_id') or '—'}\n"
        f"💰 <b>Price:</b> {'${:.2f}'.format(price) if price else '—'}\n"
        f"📊 <b>Stock:</b> {qty} {r.get('uom') or DEFAULT_UOM} | {loc}\n"
        f"🔧 <b>Condition:</b> {r.get('condition') or DEFAULT_CONDITION}"
    )


def get_stats():
    _ensure_loaded()
    rows = _cache_all
    total       = len(rows)
    inventoried = sum(1 for r in rows if int(r.get("quantity") or 0) > 0)
    located     = sum(1 for r in rows if r.get("storage_location", "").strip() not in ("", "UNASSIGNED"))
    with_photo  = sum(1 for r in rows if r.get("photo_url", "").strip())
    return {
        "total":        total,
        "inventoried":  inventoried,
        "located":      located,
        "with_photo":   with_photo,
        "remaining":    total - inventoried,
        "progress_pct": round(inventoried / total * 100, 1) if total else 0,
    }
