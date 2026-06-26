# 🚀 Деплой HMMWV Bot на Google Cloud Run
## Пошаговая инструкция через gcloud CLI

---

## Что происходит в каждом шаге (общая картина)

```
Ваш компьютер
     │
     │  gcloud builds submit
     ▼
[Artifact Registry]  ← упакованный контейнер (Docker-образ)
     │
     │  gcloud run deploy
     ▼
[Cloud Run]  ← бот работает 24/7, "спит" если нет запросов
     │
     ├── читает секреты из [Secret Manager]  ← токены в безопасном сейфе
     │
     └── пишет данные в [Google Sheets]
```

---

## Часть 1 — Подготовка (один раз)

### Шаг 1.1 — Установить Google Cloud CLI

**macOS:**
```bash
brew install google-cloud-sdk
```

**Windows** — скачать установщик:
[https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)

**Linux (Debian/Ubuntu):**
```bash
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

Проверка установки:
```bash
gcloud --version
```

---

### Шаг 1.2 — Авторизация и настройка проекта

```bash
# Войти в аккаунт Google
gcloud auth login

# Создать новый проект (замените YOUR_PROJECT_ID на уникальное имя)
gcloud projects create hmmwv-inventory-bot --name="HMMWV Inventory Bot"

# Установить проект активным
gcloud config set project hmmwv-inventory-bot

# Привязать платёжный аккаунт (нужно для Artifact Registry)
# Это делается в браузере: console.cloud.google.com → Billing
# Бесплатный уровень покрывает ваши нужды, карта нужна только для верификации
```

---

### Шаг 1.3 — Включить нужные API (одна команда)

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  sheets.googleapis.com \
  drive.googleapis.com
```

⏳ Ждите 1–2 минуты пока активируются.

---

### Шаг 1.4 — Создать репозиторий в Artifact Registry

```bash
gcloud artifacts repositories create hmmwv-repo \
  --repository-format=docker \
  --location=us-central1 \
  --description="HMMWV Inventory Bot Docker images"
```

---

## Часть 2 — Секреты (Secret Manager)

Никогда не храним токены в коде или переменных окружения в открытом виде.
Secret Manager — это зашифрованный сейф внутри вашего Google Cloud аккаунта.

### Шаг 2.1 — Загрузить секреты

```bash
# Telegram Bot Token
echo -n "ВАШ_ТОКЕН_ОТ_BOTFATHER" | \
  gcloud secrets create BOT_TOKEN \
  --data-file=-

# Google Sheet ID
echo -n "ВАШ_GOOGLE_SHEET_ID" | \
  gcloud secrets create GOOGLE_SHEET_ID \
  --data-file=-

# Название листа
echo -n "Inventory" | \
  gcloud secrets create GOOGLE_SHEET_NAME \
  --data-file=-

# JSON-ключ сервисного аккаунта Google Sheets
gcloud secrets create GOOGLE_CREDENTIALS \
  --data-file=google_credentials.json
```

### Шаг 2.2 — Узнать номер проекта

```bash
gcloud projects describe hmmwv-inventory-bot --format="value(projectNumber)"
# Сохраните это число — понадобится в следующем шаге
```

### Шаг 2.3 — Дать Cloud Run доступ к секретам

```bash
# Замените НОМЕР_ПРОЕКТА на число из предыдущего шага
gcloud secrets add-iam-policy-binding BOT_TOKEN \
  --member="serviceAccount:НОМЕР_ПРОЕКТА-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_SHEET_ID \
  --member="serviceAccount:НОМЕР_ПРОЕКТА-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_SHEET_NAME \
  --member="serviceAccount:НОМЕР_ПРОЕКТА-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding GOOGLE_CREDENTIALS \
  --member="serviceAccount:НОМЕР_ПРОЕКТА-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## Часть 3 — Обновить config.py для Secret Manager

Замените содержимое `config.py` на версию ниже, которая умеет читать
секреты как из `.env` (для локальной разработки), так и из Secret Manager
(для продакшена в Cloud Run):

```python
# config.py — версия с поддержкой Google Secret Manager
import os
from dotenv import load_dotenv

load_dotenv()  # работает локально, игнорируется в Cloud Run

def _get_secret(name: str, fallback_env: str) -> str:
    """
    Сначала ищет переменную окружения (локально / Railway).
    Если не найдена — читает из Secret Manager (Cloud Run).
    """
    value = os.getenv(fallback_env)
    if value:
        return value

    # Cloud Run монтирует секреты как файлы или переменные окружения
    # Мы используем монтирование как переменные (см. gcloud run deploy ниже)
    raise ValueError(
        f"Не найдена переменная {fallback_env}. "
        f"Локально: добавьте в .env. В Cloud Run: проверьте --set-secrets."
    )

BOT_TOKEN                = _get_secret("BOT_TOKEN",               "BOT_TOKEN")
GOOGLE_SHEET_ID          = _get_secret("GOOGLE_SHEET_ID",         "GOOGLE_SHEET_ID")
GOOGLE_SHEET_NAME        = os.getenv("GOOGLE_SHEET_NAME",         "Inventory")
GOOGLE_CREDENTIALS_FILE  = os.getenv("GOOGLE_CREDENTIALS_FILE",   "google_credentials.json")
LOCAL_CSV_PATH           = os.getenv("LOCAL_CSV_PATH",            "parts_db.csv")
OCR_LANGUAGES            = ["en"]
OCR_USE_GPU              = os.getenv("OCR_USE_GPU", "false").lower() == "true"
```

---

## Часть 4 — Сборка и деплой

### Шаг 4.1 — Перейти в папку проекта

```bash
cd путь/к/hmmwv_bot

# Убедитесь, что все файлы на месте:
ls -la
# Должны быть: bot.py, config.py, ocr_module.py, matcher.py,
#              sheets_module.py, parts_db.csv, Dockerfile, requirements.txt
```

### Шаг 4.2 — Собрать Docker-образ в облаке

```bash
# Cloud Build сам собирает образ — ничего не нужно устанавливать локально
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/hmmwv-inventory-bot/hmmwv-repo/hmmwv-bot:latest

# ⏳ Это займёт 5–10 минут (первый раз — скачивает базовый образ и зависимости)
# При повторных деплоях будет быстрее благодаря кэшированию слоёв Docker
```

### Шаг 4.3 — Задеплоить на Cloud Run

```bash
# Замените НОМЕР_ПРОЕКТА на ваш номер проекта
gcloud run deploy hmmwv-bot \
  --image us-central1-docker.pkg.dev/hmmwv-inventory-bot/hmmwv-repo/hmmwv-bot:latest \
  --region us-central1 \
  --platform managed \
  --no-allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --timeout 300 \
  --set-secrets="BOT_TOKEN=BOT_TOKEN:latest,\
GOOGLE_SHEET_ID=GOOGLE_SHEET_ID:latest,\
GOOGLE_SHEET_NAME=GOOGLE_SHEET_NAME:latest"
```

**Объяснение параметров:**
- `--memory 2Gi` — EasyOCR требует ~1.5 ГБ памяти для модели
- `--min-instances 0` — "спит" когда нет запросов (экономия)
- `--max-instances 3` — не более 3 копий одновременно
- `--timeout 300` — 5 минут на обработку (OCR может быть медленным)
- `--no-allow-unauthenticated` — только ваш бот может вызывать сервис

---

## Часть 5 — Проверка

### Посмотреть логи в реальном времени:
```bash
gcloud run services logs tail hmmwv-bot --region us-central1
```

### Посмотреть статус сервиса:
```bash
gcloud run services describe hmmwv-bot --region us-central1
```

### Перезапустить после изменений в коде:
```bash
# Пересобрать + задеплоить (две команды из шагов 4.2 и 4.3)
gcloud builds submit --tag us-central1-docker.pkg.dev/hmmwv-inventory-bot/hmmwv-repo/hmmwv-bot:latest
gcloud run deploy hmmwv-bot --image us-central1-docker.pkg.dev/hmmwv-inventory-bot/hmmwv-repo/hmmwv-bot:latest --region us-central1
```

---

## Часть 6 — Дать доступ другу

Ничего особенного делать не нужно. Просто отправьте ему ссылку:

```
t.me/ваш_bot_username
```

Он открывает Telegram, находит бота, нажимает /start и начинает сканировать.
Все данные пишутся в вашу Google Таблицу.

Если хотите ограничить доступ только для определённых людей — скажите,
добавим проверку по Telegram user_id в bot.py.

---

## Примерная стоимость (Free Tier)

| Сервис | Бесплатно | Ваше использование |
|--------|-----------|-------------------|
| Cloud Run | 2 млн запросов/мес | ~1000/мес |
| Cloud Build | 120 мин/день | ~10 мин/деплой |
| Artifact Registry | 0.5 ГБ | ~1.5 ГБ (~$0.10/мес) |
| Secret Manager | 6 секретов | 4 секрета ✅ |

**Итого:** практически бесплатно. Artifact Registry может стоить ~$0.10/месяц.

---

## Если что-то пошло не так

| Ошибка | Решение |
|--------|---------|
| `PERMISSION_DENIED` | Запустите шаг 2.3 снова, проверьте НОМЕР_ПРОЕКТА |
| `Out of memory` | Увеличьте `--memory` до `4Gi` |
| `Container failed to start` | `gcloud run services logs tail hmmwv-bot` — смотрите ошибку |
| Бот не отвечает | Проверьте BOT_TOKEN в Secret Manager |
