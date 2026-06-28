import logging
import re

from config import DEFAULT_CONDITION, DEFAULT_UOM, SYSTEM_SHORT

logger = logging.getLogger(__name__)

# Supabase client — lazy init
_supabase = None

def _get_db():
    global _supabase
    if _supabase:
        return _supabase
    from supabase import create_client
    from config import SUPABASE_URL, SUPABASE_SECRET_KEY
    _supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
    return _supabase


def load_database():
    try:
        db = _get_db()
        res = db.table("inventory").select("id", count="exact").execute()
        count = res.count or 0
        logger.info("inventory table: %d parts", count)
        return count
    except Exception as e:
        logger.error("load_database error: %s", e)
        return 0


def search_part(query):
    if not query or not query.strip():
        return None

    db  = _get_db()
    q   = query.strip().upper()
    digits = re.sub(r"\D", "", q)

    # Try NSN 13-digit format
    if len(digits) == 13:
        nsn = f"{digits[0:4]}-{digits[4:6]}-{digits[6:9]}-{digits[9:13]}"
        res = db.table("inventory").select("*").eq("nsn", nsn).limit(1).execute()
        if res.data:
            return res.data[0]

    # Try exact NSN
    res = db.table("inventory").select("*").eq("nsn", q).limit(1).execute()
    if res.data:
        return res.data[0]

    # Try exact MPN
    res = db.table("inventory").select("*").eq("mpn", q).limit(1).execute()
    if res.data:
        return res.data[0]

    # Try partial MPN
    res = db.table("inventory").select("*").ilike("mpn", f"%{q}%").limit(1).execute()
    if res.data:
        return res.data[0]

    # Try part name
    res = db.table("inventory").select("*").ilike("part_name", f"%{q}%").limit(1).execute()
    if res.data:
        return res.data[0]

    return None


def search_multiple(query, limit=5):
    if not query or not query.strip():
        return []

    db = _get_db()
    q  = query.strip().upper()
    results = []
    seen = set()

    res = db.table("inventory").select("*").ilike("mpn", f"%{q}%").limit(limit).execute()
    for r in (res.data or []):
        if r["id"] not in seen:
            results.append(r)
            seen.add(r["id"])

    if len(results) < limit:
        res = db.table("inventory").select("*").ilike("part_name", f"%{q}%").limit(limit).execute()
        for r in (res.data or []):
            if r["id"] not in seen:
                results.append(r)
                seen.add(r["id"])

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
        return True
    except Exception as e:
        logger.error("update_part_in_db error: %s", e)
        return False


def format_part_card(r):
    price = float(r.get("unit_price") or 0)
    qty   = r.get("quantity") or 0
    loc   = r.get("storage_location") or "not set"
    mpn   = r.get("mpn") or r.get("part_number") or "N/A"
    name  = r.get("part_name") or r.get("name") or "Unknown"
    cat   = r.get("category_section") or r.get("category") or ""

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
    try:
        db = _get_db()
        rows = db.table("inventory").select("quantity,storage_location,photo_url").execute().data or []
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
    except Exception as e:
        logger.error("get_stats error: %s", e)
        return {"total":0,"inventoried":0,"located":0,"with_photo":0,"remaining":0,"progress_pct":0}
