# OMNI Inventory Bot

AI-powered universal inventory and parts tracking system via Telegram.

Scan a part number or photo → bot identifies it → log quantity, location, photo → data saved to Supabase → export audit-ready Excel anytime.

Works for any parts database: military, industrial, aviation, heavy equipment.

---

## How It Works

```
Warehouse worker
      │
      │ types NSN / MPN in Telegram, or sends a photo
      ▼
  Telegram Bot ──── OCR + Gemini Vision identifies the part
      │
      │ asks: quantity → location → photo
      ▼
   Supabase ──── stores inventory data permanently
      │
      │ /export command
      ▼
  Excel File ──── audit-ready, 4 sheets
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/checkin` | Start inventory: scan → confirm → quantity → location → photo |
| `/find [NSN or MPN]` | Quick part lookup |
| `/audit [query]` | Search by location, category, or ID |
| `/report` | Warehouse summary with totals |
| `/export` | Download full audit Excel package |
| `/progress` | How much of the inventory is done |

---

## Tech Stack

| Tool | Purpose | Cost |
|---|---|---|
| Python 3.11 + aiogram | Telegram bot framework | Free |
| EasyOCR | Read text from label photos | Free |
| Google Gemini Vision | AI part identification fallback | Free tier |
| Supabase | PostgreSQL database | Free tier |
| Google Cloud Run | Serverless hosting (sleeps when idle) | ~$0/month |
| Google Secret Manager | Secure API key storage | Free tier |
| Google Cloud Build | Auto-deploy from GitHub | Free tier |

---

## Project Files

| File | What it does |
|---|---|
| `bot.py` | Main bot — all Telegram commands and conversation flow |
| `checkin.py` | Parts search — loads `parts_db.csv`, searches by NSN/MPN |
| `sheets_module.py` | Supabase integration + Excel export |
| `config.py` | Reads all settings from environment variables |
| `matcher.py` | Extracts NSN/MPN from OCR text using regex |
| `ocr_module.py` | EasyOCR wrapper — reads text from label photos |
| `gemini_vision.py` | Gemini Vision fallback — identifies parts visually |
| `webflis.py` | Fetches part prices from public military databases |
| `build_db.py` | Utility to extend parts_db.csv from external sources |
| `parts_db.csv` | Your parts database — replace with your own data |
| `Dockerfile` | Container build instructions |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for environment variables |

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/Agora141/OMNI-Inventory-bot.git
cd OMNI-Inventory-bot
```

### 2. Set up environment variables

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

### 3. Set up Supabase

1. Register at [supabase.com](https://supabase.com) → create project
2. Go to **SQL Editor** and run:

```sql
CREATE TABLE inventory (
    id SERIAL PRIMARY KEY,
    inventory_id TEXT UNIQUE NOT NULL,
    nsn TEXT, mpn TEXT, cage_code TEXT,
    part_name TEXT, category_section TEXT,
    quantity INTEGER DEFAULT 0,
    uom TEXT DEFAULT 'EA',
    storage_location TEXT DEFAULT 'UNASSIGNED',
    unit_price NUMERIC(10,2) DEFAULT 0,
    total_value NUMERIC(10,2) DEFAULT 0,
    condition TEXT DEFAULT 'NOS',
    photo_url TEXT,
    last_updated TIMESTAMP DEFAULT NOW(),
    last_operator TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE scan_log (
    id SERIAL PRIMARY KEY,
    inventory_id TEXT, scan_date TIMESTAMP DEFAULT NOW(),
    operator TEXT, user_id TEXT, nsn TEXT, mpn TEXT,
    cage_code TEXT, part_name TEXT, category_section TEXT,
    quantity INTEGER, uom TEXT, storage_location TEXT,
    condition TEXT, unit_price NUMERIC(10,2),
    total_value NUMERIC(10,2), photo_url TEXT, data_source TEXT
);

ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_full_access" ON inventory FOR ALL USING (true);
CREATE POLICY "service_full_access" ON scan_log FOR ALL USING (true);
```

3. Go to **Settings → API** → copy:
   - Project URL → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SECRET_KEY`

### 4. Add your parts database

Replace `parts_db.csv` with your data. Required columns:

```
nsn, part_number, name, category, unit, unit_price
```

### 5. Deploy to Google Cloud Run

See [DEPLOY.md](DEPLOY.md) for full step-by-step instructions.

---

## Deploy Summary

```bash
# Enable APIs
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# Create Artifact Registry repo
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker \
  --location=us-east4

# Add secrets
echo -n "YOUR_BOT_TOKEN" | gcloud secrets create BOT_TOKEN --data-file=-
echo -n "YOUR_SUPABASE_URL" | gcloud secrets create SUPABASE_URL --data-file=-
echo -n "YOUR_SUPABASE_KEY" | gcloud secrets create SUPABASE_SECRET_KEY --data-file=-
echo -n "YOUR_GEMINI_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=-

# Deploy (or use Cloud Run continuous deploy from GitHub)
gcloud run deploy omni-inventory-bot \
  --source . \
  --region us-east4 \
  --memory 2Gi \
  --min-instances 0 \
  --max-instances 3 \
  --set-secrets="BOT_TOKEN=BOT_TOKEN:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SECRET_KEY=SUPABASE_SECRET_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest"
```

---

## Known Issues

**`denied: repo does not exist`**
Create Artifact Registry repo first (see Deploy Summary above).

**Push fails with permission error**
Add `Artifact Registry Administrator` role to your compute service account in IAM.

**Build passes but bot doesn't respond**
If using webhook mode, set the webhook URL after deploy:
```
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<CLOUD_RUN_URL>
```

**Out of memory**
Increase `--memory` to `4Gi` — EasyOCR needs ~1.5 GB for the model.

---

## Condition Codes

| Code | Meaning |
|---|---|
| NOS | New Old Stock |
| A | Serviceable |
| Used | Used, functional |
| Take-off | Removed from equipment |
| Unserviceable | Not functional |

---

## License

MIT — use freely, adapt for your warehouse.
