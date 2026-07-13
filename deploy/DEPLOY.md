# Deployment runbook (no domain needed)

Frontend on Vercel, backend on a Hetzner VPS. No domain name required: Vercel
forwards API calls to the VPS behind the scenes, so the browser only ever sees
Vercel's HTTPS.

```
Browser ──HTTPS──▶ Vercel (website)
                     │  forwards /api/* server-side
                     ▼
                   Hetzner VPS  ──▶  FastAPI + trained model   (http, plain IP)
```

## Prerequisites

1. A **Hetzner VPS** (Ubuntu 22.04/24.04). 4 GB RAM is comfortable for the model.
2. A **Vercel** account.
3. That's it — no domain, no certificates.

---

## Part A — Backend on the VPS

### A1. Install Docker
SSH in (`ssh root@<VPS_IP>`), then:
```bash
curl -fsSL https://get.docker.com | sh
```

### A2. Open the backend port in Hetzner's firewall
In the Hetzner Cloud console, allow inbound **TCP 8000** (or use `ufw allow 8000`).

### A3. Get the code
```bash
git clone https://github.com/NandithReddy/secure-patient-intake.git
cd secure-patient-intake
```

### A4. Get the trained model onto the VPS
The model is not in git (large, gitignored). Pick one:

**Option 1 — copy it from your Mac** (run ON YOUR MAC):
```bash
rsync -av --exclude checkpoints \
  models/deid-roberta/ root@<VPS_IP>:/root/secure-patient-intake/models/deid-roberta/
```

**Option 2 — retrain it on the VPS** (slower on CPU, tiny dataset so still fine):
```bash
pip install -e '.[ml]'
python3 -m deid.train --base-model roberta-base --out models/deid-roberta --n-synth 200 --epochs 6 --use-cpu
```

> Skip the model and the backend still runs — it falls back to the rule redactor
> and prints a warning. The live demo works, just with the weaker redactor. You
> can add the model later.

### A5. Configure secrets
```bash
cd deploy
cp .env.example .env
nano .env      # generate the two secrets (commands are in the file), paste them in
```

### A6. Start it
```bash
docker compose up -d --build
```
Check it (from the VPS):
```bash
curl http://localhost:8000/api/health
# {"status":"ok","detector":"transformer:deid-roberta","detector_is_local":true}
```
If `detector` says `rules`, the model wasn't found — revisit A4.

---

## Part B — Frontend on Vercel

### B1. Tell Vercel where the backend is
In `frontend/vercel.json`, replace `YOUR_VPS_IP` with your Hetzner server's IP.
Commit and push that change (it's just a public IP, safe to commit).

### B2. Import the repo
In Vercel: **Add New → Project → import `secure-patient-intake`**.
Set **Root Directory** to `frontend`. Leave everything else default.
**Do not** set `VITE_API_URL` — the app calls `/api` on its own domain, and
`vercel.json` forwards that to your VPS.

### B3. Deploy
Vercel builds and gives you a URL like `https://secure-patient-intake.vercel.app`.

---

## Part C — Test it

Open your Vercel URL, log in as `clinician / clinician123`, and try the Studio.
If the API calls work, you're done.

---

## Everyday commands (on the VPS)

```bash
docker compose logs -f backend                        # watch logs
docker compose restart backend                        # restart after a config change
git pull && docker compose up -d --build              # deploy new code
docker compose down                                   # stop (data volume is kept)
```

## Honest notes
- **The backend is publicly reachable on `http://<VPS_IP>:8000` and the
  Vercel→VPS hop is not encrypted.** That's acceptable here because the data is
  **synthetic** and the API requires login. Do **not** put real patient data on
  this setup — that needs HTTPS end-to-end, a security review, a signed BAA, and
  a lawyer.
- Want proper end-to-end HTTPS later? Get a domain (even a free one), point it at
  the VPS, and put Caddy in front — it provisions HTTPS automatically. Ask me and
  I'll add that back.
- **Data lives in the `deid-data` Docker volume**, not the repo — it survives
  rebuilds.
