import asyncio
import csv as csv_module
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, Message, PhotoSize
from aiogram.utils.keyboard import InlineKeyboardBuilder

from checkin import (
    format_part_card, get_stats, load_database,
    search_multiple, search_part, update_part_in_db,
)
from config import (
    BOT_TOKEN, DEFAULT_CONDITION, DEFAULT_UOM,
    LOCAL_CSV_PATH, OCR_MIN_TEXT_LENGTH,
    SYSTEM_NAME, SYSTEM_SHORT,
)
from gemini_vision import identify_part_visually
from matcher import find_part
from ocr_module import extract_text_from_image
from sheets_module import (
    append_scan_log, export_audit_excel,
    get_dashboard_summary, update_inventory,
)
from webflis import get_unit_price

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())


class CheckinFlow(StatesGroup):
    waiting_query     = State()
    waiting_confirm   = State()
    waiting_quantity  = State()
    waiting_location  = State()
    waiting_condition = State()
    waiting_photo     = State()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    s = get_stats()
    await message.answer(
        f"👋 <b>{SYSTEM_NAME}</b>\n\n"
        f"📦 База: <b>{s['total']:,}</b> позиций\n"
        f"✅ Проинвентаризировано: <b>{s['inventoried']:,}</b> ({s['progress_pct']}%)\n"
        f"📍 С ячейкой: <b>{s['located']:,}</b>\n"
        f"📸 С фото: <b>{s['with_photo']:,}</b>\n\n"
        "/checkin — инвентаризировать\n"
        "/find [номер] — найти\n"
        "/audit [запрос] — поиск\n"
        "/report — итоги\n"
        "/export — Excel\n"
        "/progress — прогресс",
        parse_mode="HTML",
    )


@dp.message(Command("checkin"))
async def cmd_checkin(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        await _do_search(message, state, args[1].strip())
        return
    await state.set_state(CheckinFlow.waiting_query)
    await message.answer(
        "Введите <b>NSN</b> или <b>MPN</b>:\n\n"
        "<code>2530-01-234-5678</code>\n"
        "<code>5705684</code>\n"
        "<code>MS90725-6</code>",
        parse_mode="HTML",
    )


@dp.message(CheckinFlow.waiting_query)
async def handle_query(message: Message, state: FSMContext):
    await _do_search(message, state, message.text.strip())


async def _do_search(message: Message, state: FSMContext, query: str):
    part = search_part(query)

    if part:
        await state.update_data(part=part, query=query)
        await state.set_state(CheckinFlow.waiting_confirm)

        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Да", callback_data="ci_yes")
        kb.button(text="🔄 Похожие", callback_data="ci_similar")
        kb.button(text="❌ Отмена", callback_data="ci_cancel")
        kb.adjust(2, 1)

        await message.answer(
            f"{format_part_card(part)}\n\nЭта деталь?",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
        return

    similar = search_multiple(query, 5)
    if similar:
        await state.update_data(similar=similar, query=query)
        await state.set_state(CheckinFlow.waiting_confirm)

        kb = InlineKeyboardBuilder()
        for i, r in enumerate(similar):
            mpn  = r.get("part_number", r.get("mpn", "N/A"))
            name = r.get("name", r.get("part_name", ""))[:28]
            kb.button(text=f"{mpn} — {name}", callback_data=f"ci_pick_{i}")
        kb.button(text="❌ Ничего", callback_data="ci_cancel")
        kb.adjust(1)

        await message.answer(
            f"Точного совпадения нет для <code>{query}</code>\n\nПохожие:",
            parse_mode="HTML",
            reply_markup=kb.as_markup(),
        )
        return

    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Попробовать снова", callback_data="ci_retry")
    kb.button(text="📸 Фото этикетки", callback_data="ci_photo")
    kb.adjust(1)
    await message.answer(
        f"<code>{query}</code> не найдено.\n\nПроверьте номер или отправьте фото.",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@dp.callback_query(F.data == "ci_yes")
async def cb_yes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup()
    await state.set_state(CheckinFlow.waiting_quantity)
    await callback.message.answer("Сколько штук?")


@dp.callback_query(F.data.startswith("ci_pick_"))
async def cb_pick(callback: CallbackQuery, state: FSMContext):
    idx  = int(callback.data.split("_")[-1])
    data = await state.get_data()
    similar = data.get("similar", [])
    if idx >= len(similar):
        await callback.answer("Ошибка")
        return
    part = similar[idx]
    await state.update_data(part=part)
    await state.set_state(CheckinFlow.waiting_confirm)
    await callback.answer()
    await callback.message.edit_reply_markup()

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Да", callback_data="ci_yes")
    kb.button(text="❌ Отмена", callback_data="ci_cancel")
    kb.adjust(2)

    await callback.message.answer(
        f"{format_part_card(part)}\n\nВерно?",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@dp.callback_query(F.data == "ci_similar")
async def cb_similar(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    similar = search_multiple(data.get("query", ""), 5)
    await callback.answer()
    if not similar:
        await callback.message.answer("Похожих не найдено.")
        return
    kb = InlineKeyboardBuilder()
    for i, r in enumerate(similar):
        mpn  = r.get("part_number", r.get("mpn", "N/A"))
        name = r.get("name", r.get("part_name", ""))[:28]
        kb.button(text=f"{mpn} — {name}", callback_data=f"ci_pick_{i}")
    kb.button(text="❌ Отмена", callback_data="ci_cancel")
    kb.adjust(1)
    await state.update_data(similar=similar)
    await callback.message.answer("Похожие:", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "ci_cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Отменено. /checkin — начать заново.")


@dp.callback_query(F.data == "ci_retry")
async def cb_retry(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(CheckinFlow.waiting_query)
    await callback.message.answer("Введите NSN или MPN:")


@dp.callback_query(F.data == "ci_photo")
async def cb_photo_mode(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer("Отправьте фото этикетки.")


@dp.message(CheckinFlow.waiting_quantity)
async def handle_qty(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) < 0:
        await message.answer("Введите целое число, например <code>15</code>", parse_mode="HTML")
        return

    qty  = int(text)
    data = await state.get_data()
    part = data["part"]
    price = float(part.get("unit_price", 0) or 0)
    await state.update_data(quantity=qty)
    await state.set_state(CheckinFlow.waiting_location)

    total = f"${price * qty:,.2f}" if price else "—"
    await message.answer(
        f"{qty} шт. | {total}\n\nУкажите ячейку хранения:\n"
        "<i>Например: <code>A-04-B-2</code> или <code>PALLET-08</code></i>",
        parse_mode="HTML",
    )


@dp.message(CheckinFlow.waiting_location)
async def handle_loc(message: Message, state: FSMContext):
    loc = message.text.strip().upper()
    if len(loc) < 2:
        await message.answer("Укажите адрес, например <code>A-04</code>", parse_mode="HTML")
        return

    await state.update_data(storage_location=loc)
    await state.set_state(CheckinFlow.waiting_condition)

    kb = InlineKeyboardBuilder()
    kb.button(text="NOS — New Old Stock",        callback_data="cond_NOS")
    kb.button(text="A — Serviceable",           callback_data="cond_A")
    kb.button(text="Used — б/у рабочее",        callback_data="cond_Used")
    kb.button(text="Take-off — снято с машины", callback_data="cond_Takeoff")
    kb.button(text="Unserviceable",             callback_data="cond_Unserviceable")
    kb.adjust(2, 2, 1)

    await message.answer(
        f"Ячейка: <b>{loc}</b>\n\nСостояние:",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@dp.callback_query(CheckinFlow.waiting_condition, F.data.startswith("cond_"))
async def handle_cond(callback: CallbackQuery, state: FSMContext):
    condition = callback.data.split("_", 1)[1]
    await state.update_data(condition=condition)
    await state.set_state(CheckinFlow.waiting_photo)
    await callback.answer()
    await callback.message.edit_reply_markup()

    data = await state.get_data()
    part = data["part"]
    await callback.message.answer(
        f"Состояние: <b>{condition}</b>\n\n"
        "📸 Сделайте фото детали или коробки.\n"
        f"<i>{part.get('name', '')[:50]} | {data.get('storage_location', '')}</i>\n\n"
        "Или напишите «пропустить».",
        parse_mode="HTML",
    )


@dp.message(CheckinFlow.waiting_photo, F.photo)
async def handle_checkin_photo(message: Message, state: FSMContext):
    data      = await state.get_data()
    await state.clear()

    part      = data["part"]
    quantity  = data.get("quantity", 0)
    location  = data.get("storage_location", "UNASSIGNED")
    condition = data.get("condition", DEFAULT_CONDITION)

    photo: PhotoSize = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    tmp  = f"/tmp/ipm_{photo.file_id}.jpg"
    await bot.download_file(file.file_path, destination=tmp)

    photo_url = f"tg://file/{photo.file_id}"
    update_part_in_db(
        part.get("inventory_id", ""), quantity, location, condition, photo_url
    )

    mpn   = part.get("part_number", part.get("mpn", "N/A"))
    price = float(part.get("unit_price", 0) or 0)
    rec   = {
        "scan_date":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "operator":         message.from_user.username or message.from_user.full_name,
        "user_id":          message.from_user.id,
        "nsn":              part.get("nsn", "N/A"),
        "mpn":              mpn,
        "cage_code":        part.get("cage_code", ""),
        "part_name":        part.get("name", part.get("part_name", "")),
        "category_section": part.get("category", part.get("category_section", "")),
        "quantity":         quantity,
        "uom":              part.get("unit", part.get("uom", DEFAULT_UOM)),
        "unit_price":       price,
        "storage_location": location,
        "condition":        condition,
        "photo_url":        photo_url,
        "data_source":      "checkin",
    }

    try:
        await asyncio.to_thread(append_scan_log, rec)
        await asyncio.to_thread(update_inventory, rec)
        sheets_ok = True
    except Exception:
        logger.exception("sheets write failed")
        sheets_ok = False

    if os.path.exists(tmp):
        os.remove(tmp)

    price_s = f"${price:,.2f}" if price else "—"
    total_s = f"${price * quantity:,.2f}" if price else "—"

    await message.answer(
        f"✅ <b>Записано</b>\n\n"
        f"{part.get('name', '')[:55]}\n"
        f"NSN: <code>{part.get('nsn', '')}</code> | MPN: <code>{mpn}</code>\n"
        f"ID: <b>{part.get('inventory_id', '')}</b> | Ячейка: <b>{location}</b>\n"
        f"{quantity} шт. × {price_s} = <b>{total_s}</b>\n"
        f"Состояние: {condition} | Фото: ✅\n"
        f"{'Sheets: ✅' if sheets_ok else 'Sheets: ⚠️ ошибка'}\n\n"
        "/checkin — следующая",
        parse_mode="HTML",
    )


@dp.message(CheckinFlow.waiting_photo, F.text)
async def skip_photo(message: Message, state: FSMContext):
    if message.text.strip().lower() in ("пропустить", "skip", "-", "нет", "no"):
        data = await state.get_data()
        await state.clear()
        part = data["part"]
        update_part_in_db(
            part.get("inventory_id", ""),
            data.get("quantity", 0),
            data.get("storage_location", "UNASSIGNED"),
            data.get("condition", DEFAULT_CONDITION),
        )
        await message.answer(
            f"✅ Записано без фото\n"
            f"<code>{part.get('nsn', '')}</code> | "
            f"{data.get('storage_location', '')} | "
            f"{data.get('quantity', 0)} шт.\n\n/checkin — следующая",
            parse_mode="HTML",
        )
    else:
        await message.answer("Отправьте фото или напишите «пропустить».")


@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    current = await state.get_state()
    if current == CheckinFlow.waiting_photo:
        await handle_checkin_photo(message, state)
        return

    await message.answer("Распознаю...")

    photo: PhotoSize = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    tmp  = f"/tmp/ipm_scan_{photo.file_id}.jpg"
    await bot.download_file(file.file_path, destination=tmp)

    part        = None
    used_gemini = False

    try:
        raw = await asyncio.to_thread(extract_text_from_image, tmp)
        if len(raw.strip()) >= OCR_MIN_TEXT_LENGTH:
            await message.answer(f"<code>{raw[:400]}</code>", parse_mode="HTML")
            part = search_part(raw.strip()) or search_part(find_part(raw) and find_part(raw).get("nsn", "") or "")

        if not part:
            gemini = await asyncio.to_thread(identify_part_visually, tmp)
            if gemini:
                part = search_part(gemini.get("nsn", "")) or gemini
                used_gemini = True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    if not part:
        await message.answer(
            "Не удалось распознать.\n/checkin [NSN или MPN] — ввести вручную"
        )
        return

    src = "AI Vision" if used_gemini else "OCR"
    await message.answer(
        f"{src}:\n\n{format_part_card(part)}\n\n"
        f"/checkin {part.get('nsn', '')}",
        parse_mode="HTML",
    )


@dp.message(Command("find"))
async def cmd_find(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("/find [NSN или MPN]")
        return
    part = search_part(args[1].strip())
    if part:
        await message.answer(format_part_card(part), parse_mode="HTML")
        return
    similar = search_multiple(args[1].strip(), 3)
    if similar:
        lines = ["Похожие:\n"]
        for r in similar:
            lines.append(f"• <code>{r.get('nsn','')}</code> — {r.get('name','')[:40]}")
        await message.answer("\n".join(lines), parse_mode="HTML")
    else:
        await message.answer(f"<code>{args[1]}</code> не найдено.", parse_mode="HTML")


@dp.message(Command("progress"))
async def cmd_progress(message: Message):
    s   = get_stats()
    pct = s["progress_pct"]
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    await message.answer(
        f"[{bar}] {pct}%\n\n"
        f"Всего: {s['total']:,}\n"
        f"Проинвентаризировано: {s['inventoried']:,}\n"
        f"С ячейкой: {s['located']:,}\n"
        f"С фото: {s['with_photo']:,}\n"
        f"Осталось: {s['remaining']:,}",
    )


@dp.message(Command("report"))
async def cmd_report(message: Message):
    try:
        summary = await asyncio.to_thread(get_dashboard_summary)
        await message.answer(summary, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@dp.message(Command("export"))
async def cmd_export(message: Message):
    await message.answer("Генерирую Excel...")
    try:
        with open(LOCAL_CSV_PATH, newline="", encoding="utf-8") as f:
            records = list(csv_module.DictReader(f))

        output = f"/tmp/{SYSTEM_SHORT}_audit.xlsx"
        await asyncio.to_thread(export_audit_excel, records, output)

        doc = FSInputFile(output, filename=f"{SYSTEM_SHORT}_Inventory_Audit.xlsx")
        await message.answer_document(
            doc,
            caption=(
                f"<b>{SYSTEM_NAME}</b>\n\n"
                "Cover Page | Inventory Master | Blank Audit Form | By Category\n\n"
                "READ-ONLY для аудиторов"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.exception("export failed")
        await message.answer(f"Ошибка: {e}")


@dp.message(Command("audit"))
async def cmd_audit(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "/audit A-04 — по ячейке\n"
            "/audit DRIVETRAIN — по категории\n"
            "/audit IPM-00042 — по ID\n"
            "/audit 2530-01-234-5678 — по NSN"
        )
        return

    q = args[1].strip().upper()
    with open(LOCAL_CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv_module.DictReader(f))

    results = [r for r in rows if
               q in r.get("storage_location", "").upper() or
               q in r.get("inventory_id", "").upper() or
               q in r.get("category", "").upper() or
               q in r.get("nsn", "").upper() or
               q in r.get("name", "").upper()]

    if not results:
        await message.answer(f"Ничего по запросу <code>{q}</code>", parse_mode="HTML")
        return

    lines = [f"<b>{len(results)} позиций</b>\n"]
    for r in results[:8]:
        lines.append(
            f"• <b>{r.get('inventory_id','')}</b> <code>{r.get('nsn','')}</code>\n"
            f"  {r.get('name','')[:45]}\n"
            f"  {r.get('storage_location','—')} | {r.get('quantity','0')} шт. | {r.get('condition','NOS')}"
        )
    if len(results) > 8:
        lines.append(f"\n<i>...ещё {len(results) - 8}. /export для полного списка.</i>")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def main():
    count = load_database()
    logger.info("%s started, %d parts loaded", SYSTEM_NAME, count)

    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    port = int(os.getenv("PORT", 8080))
    webhook_url = "https://omni-inventory-bot-54948418739.us-east4.run.app/webhook"

    await bot.set_webhook(webhook_url)
    logger.info("webhook set: %s", webhook_url)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("server started on port %d", port)

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
