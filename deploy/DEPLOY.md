# Deployment runbook

Frontend on Vercel, backend on a Hetzner VPS. The backend runs the full trained
model, the database, and the audit log in Docker, with automatic HTTPS via Caddy.

```
Vercel (website)  ──HTTPS──▶  Hetzner VPS  ──▶  Caddy ──▶ FastAPI + model
```

## Prerequisites (get these first)

1. A **domain name**, with a subdomain you can point at the VPS (e.g. `api.yourdomain.com`).
2. A **Hetzner VPS** (Ubuntu 22.04/24.04). 4 GB RAM is comfortable for serving the model.
3. A **Vercel** account.

---

## Part A — Backend on the VPS

### A1. Point the domain at the VPS
In your domain's DNS settings, add an **A record**:
`api.yourdomain.com  →  <your VPS IP address>`. Wait a few minutes for it to take effect.

### A2. Install Docker on the VPS
SSH in (`ssh root@<VPS IP>`), then:
```bash
curl -fsSL https://get.docker.com | sh
```

### A3. Get the code onto the VPS
```bash
git clone https://github.com/NandithReddy/secure-patient-intake.git
cd secure-patient-intake
```

### A4. Get the trained model onto the VPS
The model is not in git (it is large and gitignored). Two choices:

**Option 1 — copy it from your Mac** (run this ON YOUR MAC, not the VPS):
```bash
# only the essential files, not the multi-GB training checkpoints
rsync -av --exclude checkpoints \
  models/deid-roberta/ root@<VPS IP>:/root/secure-patient-intake/models/deid-roberta/
```

**Option 2 — retrain it on the VPS** (slower on CPU, but no transfer):
```bash
pip install -e '.[ml]'    # or inside a venv
python -m deid.train --base-model roberta-base --out models/deid-roberta --n-synth 200 --epochs 6 --use-cpu
```

> If you skip the model entirely, the backend still runs — it falls back to the
> rule redactor and prints a warning. The live demo works, just with the weaker
> redactor. You can add the model later.

### A5. Configure secrets
```bash
cd deploy
cp .env.example .env
nano .env          # fill in BACKEND_DOMAIN, generate the two secrets (commands are in the file)
```
Leave `DEID_CORS_ORIGINS` for now — you set it after Part B.

### A6. Start it
```bash
docker compose up -d --build
```
Caddy fetches an HTTPS certificate automatically (takes ~30 seconds the first time).
Check it:
```bash
curl https://api.yourdomain.com/api/health
# {"status":"ok","detector":"transformer:deid-roberta","detector_is_local":true}
```
If `detector` says `rules`, the model wasn't found — revisit A4.

---

## Part B — Frontend on Vercel

### B1. Import the repo
In Vercel: **Add New → Project → import `secure-patient-intake`**.
Set the **Root Directory** to `frontend`.

### B2. Set the backend URL
In the project's **Environment Variables**, add:
`VITE_API_URL = https://api.yourdomain.com`

### B3. Deploy
Vercel builds and gives you a URL like `https://secure-patient-intake.vercel.app`.

---

## Part C — Connect the two

### C1. Tell the backend to trust the Vercel site
On the VPS, edit `deploy/.env`:
```
DEID_CORS_ORIGINS=https://secure-patient-intake.vercel.app
```
Then restart just the backend:
```bash
docker compose up -d
```

### C2. Test end to end
Open your Vercel URL, log in as `clinician / clinician123`, and try the Studio.

---

## Everyday commands (on the VPS)

```bash
docker compose logs -f backend     # watch backend logs
docker compose restart backend     # restart after a config change
docker compose pull && docker compose up -d --build   # deploy new code after git pull
docker compose down                # stop everything (data in the named volume is kept)
```

## Notes
- **Data lives in the `deid-data` Docker volume**, not in the repo — it survives
  rebuilds. Back it up if it ever holds anything you care about.
- **This demo uses synthetic data.** Do not put real patient information on a
  public server without a proper security review, a signed BAA, and a lawyer.
