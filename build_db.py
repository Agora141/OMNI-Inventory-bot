"""
build_db.py — Скрипт для расширения базы parts_db.csv из внешних источников.

Запускается ВРУЧНУЮ (не ботом) когда нужно обновить базу.

Источники (в порядке приоритета):
  1. nsncenter.com  — поиск по FSC кодам HMMWV
  2. Локальные PDF-мануалы если скачаны (TM 9-2320-280-24P)

Использование:
  # Обновить существующую базу новыми записями:
  python build_db.py

  # Скачать PDF мануал и распарсить:
  python build_db.py --pdf /path/to/TM-9-2320-280-24P-1.pdf

Зависимости:
  pip install requests beautifulsoup4 pdfplumber

Где скачать мануалы БЕСПЛАТНО:
  https://archive.org/details/131-hmmwv-manuals
  Файлы: TM 9-2320-280-24P-1 (Том 1) и TM 9-2320-280-24P-2 (Том 2)
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

# FSC коды для HMMWV частей
HMMWV_FSC_CODES = [
    "2510",  # Корпус и кузов
    "2520",  # Трансмиссия и привод
    "2530",  # Тормоза, колёса, рулевое
    "2590",  # Подвеска и прочее авто
    "2815",  # Двигатель
    "2910",  # Топливная система
    "3010",  # Трансмиссионные валы
    "4330",  # Охлаждение
    "4520",  # Отопление
    "6150",  # Электрика
    "6220",  # Освещение
    "1005",  # Вооружение (башня, крепления)
]


def load_existing_csv() -> dict:
    """Загружает существующий CSV, возвращает dict {nsn: row}."""
    existing = {}
    if not CSV_PATH.exists():
        return existing
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nsn = row.get("nsn", "").strip()
            if nsn:
                existing[nsn] = row
    logger.info("Загружено записей из CSV: %d", len(existing))
    return existing


def save_csv(records: dict):
    """Сохраняет словарь записей в CSV."""
    fieldnames = ["nsn", "part_number", "name", "category", "unit", "unit_price"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records.values():
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    logger.info("Сохранено записей в CSV: %d", len(records))


def scrape_nsncenter(fsc: str, existing_nsns: set) -> list:
    """
    Парсит nsncenter.com по FSC коду.
    Возвращает список новых записей.
    
    ВАЖНО: Запускать только с реального компьютера с интернетом.
    В контейнере Claude сеть ограничена.
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

            # Ищем строки с NSN
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

                # Пытаемся извлечь название
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
                break  # Пустая страница — конец

            page += 1
            time.sleep(1)  # Вежливая пауза

        except Exception as e:
            logger.error("Ошибка scraping FSC %s page %d: %s", fsc, page, e)
            break

    return new_records


def parse_pdf_manual(pdf_path: str) -> list:
    """
    Парсит PDF мануал TM 9-2320-280-24P и извлекает NSN.
    
    Мануал можно скачать бесплатно с:
    https://archive.org/details/131-hmmwv-manuals
    
    Структура мануала:
    - Каждая деталь имеет строку вида: NSN | Название | Кол-во | Part Number
    - NSN в формате 4-2-3-4 или без дефисов
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error("Установите: pip install pdfplumber")
        return []

    records = []
    seen_nsns = set()

    logger.info("Парсинг PDF: %s", pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        logger.info("Страниц в PDF: %d", total)

        for i, page in enumerate(pdf.pages):
            if i % 50 == 0:
                logger.info("Обработано страниц: %d / %d", i, total)

            text = page.extract_text() or ""

            # Ищем NSN паттерны
            # В мануале NSN выглядит как: 2530-01-109-1022
            nsn_pattern = re.compile(r"\b(\d{4}-\d{2}-\d{3}-\d{4})\b")

            for match in nsn_pattern.finditer(text):
                nsn = match.group(1)
                if nsn in seen_nsns:
                    continue

                # Берём контекст вокруг NSN (100 символов после)
                start = match.end()
                context = text[start:start + 150].strip()

                # Убираем переносы строк
                context = re.sub(r"\s+", " ", context)

                # Пытаемся найти название — обычно идёт после NSN
                # В формате: NSN   НАЗВАНИЕ ДЕТАЛИ   QTY   PART NUMBER
                name_match = re.match(
                    r"([A-Z][A-Z0-9 ,\-/\.]{5,60}?)(?:\s{2,}|\d+\s+[A-Z0-9\-]{4,})",
                    context,
                )
                name = name_match.group(1).strip() if name_match else "See Manual"

                # Part Number — ищем буквенно-цифровой код
                pn_match = re.search(r"\b([A-Z0-9]{2,}-[A-Z0-9]{2,}|[0-9]{5,}[A-Z]?)\b", context)
                part_number = pn_match.group(1) if pn_match else "N/A"

                # Определяем категорию по FSC (первые 4 цифры NSN)
                fsc = nsn[:4]
                category = _fsc_to_category(fsc)

                records.append({
                    "nsn":         nsn,
                    "part_number": part_number,
                    "name":        name[:80],  # Обрезаем длинные названия
                    "category":    category,
                    "unit":        "EA",
                    "unit_price":  0.0,  # Цены нет в мануале, нужен WEBFLIS
                })
                seen_nsns.add(nsn)

    logger.info("Найдено уникальных NSN в PDF: %d", len(records))
    return records


def _fsc_to_category(fsc: str) -> str:
    """Конвертирует FSC код в читаемую категорию."""
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
    parser = argparse.ArgumentParser(description="Обновление базы запчастей HMMWV")
    parser.add_argument("--pdf",  help="Путь к PDF мануалу TM 9-2320-280-24P")
    parser.add_argument("--scrape", action="store_true",
                        help="Парсить nsncenter.com (нужен интернет)")
    parser.add_argument("--stats", action="store_true",
                        help="Показать статистику по текущей базе")
    args = parser.parse_args()

    existing = load_existing_csv()

    if args.stats or (not args.pdf and not args.scrape):
        # Показываем статистику текущей базы
        print(f"\n{'='*50}")
        print(f"📊 Статистика базы: {CSV_PATH}")
        print(f"{'='*50}")
        print(f"Всего записей: {len(existing)}")

        categories = {}
        for row in existing.values():
            cat = row.get("category", "Unknown")
            categories[cat] = categories.get(cat, 0) + 1

        print("\nПо категориям:")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} позиций")

        total_value = sum(
            float(r.get("unit_price", 0) or 0) for r in existing.values()
        )
        print(f"\nСуммарная стоимость всех позиций: ${total_value:,.2f}")
        print(f"{'='*50}\n")

        if not args.pdf and not args.scrape:
            print("Использование:")
            print("  python build_db.py --stats          # статистика")
            print("  python build_db.py --pdf manual.pdf # парсить PDF")
            print("  python build_db.py --scrape         # парсить сайт (нужен интернет)")
            print()
            print("Где скачать мануалы:")
            print("  https://archive.org/details/131-hmmwv-manuals")
            print("  Файл: TM 9-2320-280-24P-1 (Том 1, ~450 MB)")
            print("  Файл: TM 9-2320-280-24P-2 (Том 2, ~430 MB)")
        return

    new_records = []
    existing_nsns = set(existing.keys())

    if args.pdf:
        pdf_records = parse_pdf_manual(args.pdf)
        new_records.extend(pdf_records)
        logger.info("Из PDF получено новых записей: %d", len(pdf_records))

    if args.scrape:
        for fsc in HMMWV_FSC_CODES:
            logger.info("Парсинг FSC %s...", fsc)
            fsc_records = scrape_nsncenter(fsc, existing_nsns)
            new_records.extend(fsc_records)
            logger.info("FSC %s: получено %d новых записей", fsc, len(fsc_records))
            time.sleep(2)

    if new_records:
        for rec in new_records:
            nsn = rec["nsn"]
            if nsn not in existing:
                existing[nsn] = rec

        save_csv(existing)
        logger.info("✅ Добавлено новых записей: %d. Всего в базе: %d",
                    len(new_records), len(existing))
    else:
        logger.info("Новых записей не найдено.")


if __name__ == "__main__":
    main()
