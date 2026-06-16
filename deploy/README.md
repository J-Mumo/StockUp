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
cp .env.production.example .env
nano .env   # set POSTGRES_PASSWORD, JWT_SECRET_KEY, OPENAI_API_KEY, etc.

# Build and start everything (first build pulls the ~1GB Playwright base, takes a few minutes)
docker compose up -d --build

# Watch logs
docker compose logs -f api worker beat
```

> The file **must** be named `.env` (not `.env.production`). Docker Compose only
> auto-loads `.env` for every subcommand (`ps`, `logs`, `exec`, ...). If you've
> already created `.env.production`, just symlink it:
> `ln -s .env.production .env`

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

After any code push from your laptop, update the VM in one shot:

```bash
stockup-update
```

That alias (installed by `setup-vm.sh` at `/usr/local/bin/stockup-update`) does
`git pull` + `docker compose up -d --build` against `~/stockup`. Override the
directory with `STOCKUP_DIR=/path/to/repo stockup-update` if you cloned elsewhere.

Other useful commands:

```bash
# Restart a single service
docker compose restart worker

# One-off shell
docker compose exec api bash

# Tail logs
docker compose logs -f api worker beat

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

## 6. Migrating / restoring Postgres data

Use this to seed the VM with your local laptop database, restore from a backup
dump, or move data between two VMs. The dump file is portable across Postgres 16
hosts (laptop ↔ container ↔ another VM).

### Export from laptop (PowerShell)

```powershell
# Set local DB password (from backend/.env)
$env:PGPASSWORD = "stockup123"

# Custom-format dump (compressed, faster to restore than plain SQL)
pg_dump -h localhost -U stockup -d stockup -F c -f stockup.dump
```

If `pg_dump` isn't on PATH, full path is `C:\Program Files\PostgreSQL\16\bin\pg_dump.exe`.

Copy to the VM:

```powershell
scp -i stockup.pem stockup.dump azureuser@<vm-ip>:~/stockup.dump
```

### Import into the VM's container

```bash
cd ~/stockup

# Move the dump into the postgres container
docker compose cp ~/stockup.dump postgres:/tmp/stockup.dump

# Drop and recreate the target DB
docker compose exec postgres psql -U stockup -d postgres -c "DROP DATABASE stockup;"
docker compose exec postgres psql -U stockup -d postgres -c "CREATE DATABASE stockup OWNER stockup;"

# Restore (--no-owner / --no-privileges keeps it portable across users)
docker compose exec postgres pg_restore -U stockup -d stockup \
    --no-owner --no-privileges /tmp/stockup.dump

# Clean up
docker compose exec postgres rm /tmp/stockup.dump
rm ~/stockup.dump

# Restart app containers to drop any stale connections
docker compose restart api worker beat
```

### Verify

```bash
docker compose exec postgres psql -U stockup -d stockup -c \
    "SELECT COUNT(*) FROM companies; SELECT COUNT(*) FROM price_history;"
```

> **Note:** `api` always runs `alembic upgrade head` on startup. If the imported
> dump is on an older schema revision than the deployed image, pending migrations
> apply automatically. If it's *newer*, the upgrade is a no-op — but you may need
> to deploy newer backend code before the API can read all columns.

## 7. Cost control

- Stop the VM from the Azure portal when you don't need it — you only pay for the disk
  (~$2.40/mo) while stopped (Deallocated).
- Once steady, buy a 1-year Reserved Instance for the VM size to save ~40%.
- Watch the meter in **Cost Management + Billing → Cost analysis**, scope to this
  resource group.

## 8. Troubleshooting

### `password authentication failed for user "stockup"` on `api` startup

The official `postgres` image **only reads `POSTGRES_PASSWORD` on the very first
initialization** of its data directory. If you ever started the stack with a
different (or blank) password and then changed `.env`, the volume still has the
original credentials baked in.

For an empty/fresh DB, wipe and redo:

```bash
docker compose down -v
docker compose up -d --build
```

If the DB already holds data you want to keep, change the password *inside*
postgres instead:

```bash
docker compose exec postgres psql -U stockup -d postgres -c \
    "ALTER USER stockup WITH PASSWORD 'whatever-is-in-your-env';"
docker compose restart api worker beat
```

### `WARN[0000] The "POSTGRES_PASSWORD" variable is not set` on every compose command

Docker Compose only auto-loads a file literally named `.env`. The `--env-file`
flag is only honored by `up`/`run`, not by `ps`/`logs`/`exec`. Make sure your
production env file is named `.env` (not `.env.production`):

```bash
mv .env.production .env      # or:  ln -s .env.production .env
```

### Frontend `npm run dev` shows proxy errors

The Vite dev server proxies `/api/*` to `http://localhost:8000`. Open the SSH
tunnel from your laptop first:

```powershell
ssh -i stockup.pem -L 8000:localhost:8000 azureuser@<vm-ip>
```

Verify with `curl http://localhost:8000/health` before retrying `npm run dev`.

### Generating random secrets on Windows (no OpenSSL)

`openssl rand -hex 24` doesn't ship with PowerShell. Either run it on the VM,
or use this PowerShell substitute:

```powershell
# 48 hex chars (good for POSTGRES_PASSWORD)
-join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })

# 96 hex chars (good for JWT_SECRET_KEY)
-join ((1..96) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
```
