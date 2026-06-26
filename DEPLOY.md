# Deploying OMNI Inventory Bot to Google Cloud Run

---

## Overview

```
Your machine
     │
     │  git push → Cloud Build trigger
     ▼
[Artifact Registry]  ← built Docker image
     │
     │  auto-deploy
     ▼
[Cloud Run]  ← bot runs here, sleeps when idle
     │
     ├── reads secrets from [Secret Manager]
     │
     └── writes data to [Supabase]
```

---

## Part 1 — Prerequisites

### 1.1 Install Google Cloud CLI

**macOS:**
```bash
brew install google-cloud-sdk
```

**Windows:**
[https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)

**Linux (Debian/Ubuntu):**
```bash
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

Verify:
```bash
gcloud --version
```

---

### 1.2 Authenticate and set project

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

---

### 1.3 Enable required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com
```

---

### 1.4 Create Artifact Registry repository

```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker \
  --location=us-east4 \
  --description="OMNI Inventory Bot images"
```

---

## Part 2 — Secrets

Never store API keys in code or environment files. Use Secret Manager.

### 2.1 Add secrets

```bash
echo -n "YOUR_BOT_TOKEN" | gcloud secrets create BOT_TOKEN --data-file=-
echo -n "YOUR_SUPABASE_URL" | gcloud secrets create SUPABASE_URL --data-file=-
echo -n "YOUR_SUPABASE_SERVICE_ROLE_KEY" | gcloud secrets create SUPABASE_SECRET_KEY --data-file=-
echo -n "YOUR_GEMINI_API_KEY" | gcloud secrets create GEMINI_API_KEY --data-file=-
```

### 2.2 Grant Cloud Run access to secrets

```bash
# Get your project number first
gcloud projects describe YOUR_PROJECT_ID --format="value(projectNumber)"

# Then grant access (replace PROJECT_NUMBER)
for SECRET in BOT_TOKEN SUPABASE_URL SUPABASE_SECRET_KEY GEMINI_API_KEY; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done
```

### 2.3 Grant Artifact Registry access

In Google Cloud Console → IAM, find the compute service account
(`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) and add the role
**Artifact Registry Administrator**.

---

## Part 3 — Supabase Setup

1. Register at [supabase.com](https://supabase.com) and create a project
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

3. Go to **Settings → API** and copy:
   - Project URL → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SECRET_KEY`

---

## Part 4 — Deploy

### Option A: Continuous deploy from GitHub (recommended)

1. Go to **Cloud Run → Create Service → Continuously deploy from repository**
2. Connect GitHub → select your repo
3. Build settings:
   - Branch: `main`
   - Build type: **Dockerfile**
   - Source location: `/`
4. Service settings:
   - Region: `us-east4`
   - Min instances: `0`
   - Max instances: `3`
   - Memory: `2Gi`
   - Timeout: `300s`
   - Authentication: Allow unauthenticated
5. Under **Variables & Secrets** → reference all 4 secrets from Secret Manager
6. In **Cloud Build trigger settings**, set image name to:
   ```
   us-east4-docker.pkg.dev/YOUR_PROJECT_ID/cloud-run-source-deploy/ipm-bot:$COMMIT_SHA
   ```

### Option B: Manual deploy via CLI

```bash
# Build and push
gcloud builds submit \
  --tag us-east4-docker.pkg.dev/YOUR_PROJECT_ID/cloud-run-source-deploy/ipm-bot:latest

# Deploy
gcloud run deploy omni-inventory-bot \
  --image us-east4-docker.pkg.dev/YOUR_PROJECT_ID/cloud-run-source-deploy/ipm-bot:latest \
  --region us-east4 \
  --memory 2Gi \
  --min-instances 0 \
  --max-instances 3 \
  --timeout 300 \
  --allow-unauthenticated \
  --set-secrets="BOT_TOKEN=BOT_TOKEN:latest,SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SECRET_KEY=SUPABASE_SECRET_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest"
```

---

## Part 5 — Verify

```bash
# Stream live logs
gcloud run services logs tail omni-inventory-bot --region us-east4

# Check service status
gcloud run services describe omni-inventory-bot --region us-east4
```

---

## Part 6 — Add your parts database

Replace `parts_db.csv` with your own data. Required columns:

```
nsn, part_number, name, category, unit, unit_price
```

Leave `quantity` and `storage_location` empty — they get filled during inventory.

---

## Estimated cost

| Service | Free tier | Expected usage |
|---|---|---|
| Cloud Run | 2M requests/month | ~1000/month |
| Cloud Build | 120 min/day | ~10 min/deploy |
| Artifact Registry | 0.5 GB | ~1.5 GB (~$0.10/month) |
| Secret Manager | 6 secrets | 4 secrets |
| Supabase | 500 MB DB | varies |

**Total: ~$0 with free credits.**

---

## Troubleshooting

| Error | Fix |
|---|---|
| `denied: repo does not exist` | Create Artifact Registry repo (Part 1.4) |
| Push fails with permission error | Add Artifact Registry Administrator role (Part 2.3) |
| `Out of memory` | Increase `--memory` to `4Gi` |
| `Container failed to start` | Check logs: `gcloud run services logs tail omni-inventory-bot` |
| Bot not responding | Check BOT_TOKEN in Secret Manager |
