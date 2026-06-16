# StockUp — Azure VM deployment

Single-VM deployment running api + celery worker + celery beat + postgres + redis in
Docker Compose. API binds to loopback only; access from your laptop via SSH tunnel.

## 0. Prep your laptop

The `.pem` you downloaded from Azure is your SSH key. Lock its permissions:

```powershell
icacls stockup.pem /inheritance:r
icacls stockup.pem /grant:r "$($env:USERNAME):(R)"
```

## 1. First-time VM bootstrap

SSH into the VM (replace IP):

```powershell
ssh -i stockup.pem azureuser@<vm-public-ip>
```

On the VM:

```bash
# Clone the repo (use a deploy key or HTTPS PAT for private repos)
git clone https://github.com/<you>/stockup.git ~/stockup
cd ~/stockup

# Install Docker, configure firewall, enable security updates
bash deploy/setup-vm.sh

# IMPORTANT: log out and back in once so your user picks up the docker group
exit
```

Re-SSH and continue:

```bash
cd ~/stockup
cp .env.production.example .env.production
nano .env.production   # set POSTGRES_PASSWORD, JWT_SECRET_KEY, OPENAI_API_KEY, etc.

# Build and start everything (first build pulls the ~1GB Playwright base, takes a few minutes)
docker compose --env-file .env.production up -d --build

# Watch logs
docker compose logs -f api worker beat
```

Migrations run automatically when the `api` container starts (`alembic upgrade head`).

## 2. Seed and backfill

```bash
docker compose exec api python -m cli.commands seed-nse
docker compose exec api python -m cli.commands backfill-prices
```

Celery beat will then keep things fresh on the daily schedule defined in
`backend/tasks/celery_app.py` (price fetch at 18:00 EAT, valuations at 19:00, etc.).

## 3. Access the UI / API from your laptop

The API is bound to `127.0.0.1:8000` on the VM — not exposed publicly. Tunnel it:

```powershell
ssh -i stockup.pem -L 8000:localhost:8000 azureuser@<vm-public-ip>
```

While that SSH session is open, on your laptop:
- API docs: http://localhost:8000/docs
- Point local frontend (`npm run dev` in `frontend/`) at `http://localhost:8000` — its
  existing CORS config already allows `localhost:5173`.

## 4. Day-to-day commands

```bash
# Update to latest code
cd ~/stockup
git pull
docker compose --env-file .env.production up -d --build

# Restart a single service
docker compose restart worker

# One-off shell
docker compose exec api bash

# Stop everything (data persists in named volumes)
docker compose down

# Wipe everything including data (DESTRUCTIVE)
docker compose down -v
```

## 5. Backups

Nightly Postgres dump to the VM disk (rotate weekly). Add to crontab with `crontab -e`:

```cron
0 2 * * * cd /home/azureuser/stockup && docker compose exec -T postgres \
  pg_dump -U stockup stockup | gzip > /home/azureuser/backups/stockup-$(date +\%Y\%m\%d).sql.gz \
  && find /home/azureuser/backups -name 'stockup-*.sql.gz' -mtime +7 -delete
```

For off-VM backup, push the latest dump to Azure Blob Storage (Cool tier, ~$0.01/GB/mo)
using `az storage blob upload` from the same cron.

## 6. Cost control

- Stop the VM from the Azure portal when you don't need it — you only pay for the disk
  (~$2.40/mo) while stopped (Deallocated).
- Once steady, buy a 1-year Reserved Instance for the VM size to save ~40%.
- Watch the meter in **Cost Management + Billing → Cost analysis**, scope to this
  resource group.
