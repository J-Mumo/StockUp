# StockUp — deployment guide

Multi-app deployment model:

- **One Hetzner Cloud VM (Ubuntu 24.04)** hosts several small apps.
- **One shared Caddy proxy** ([deploy/proxy/](proxy)) terminates TLS on ports 80/443 and routes by hostname.
- **Each app is its own Docker Compose project** (its own repo, `.env`, database, volumes, backups) joined to an external Docker network called `web` so Caddy can reach it.

```
Internet ──► :443 ──► Caddy (~/proxy) ──► web network ──► stockup / maliscope / pesatrack / ...
```

Current apps on the roadmap:

| Host | Repo | Runtime |
|---|---|---|
| `stockup.jmumo.com` | this repo | FastAPI + Vite/React, Postgres, Redis, Celery |
| `maliscope.jmumo.com` | `C:\Eng\MaliScope` | Next.js + Postgres |
| `pesatrack.jmumo.com` | `C:\Eng\PesaTrack\website` | Astro static site |

---

## Connection details (this deployment)

| Field | Value |
|---|---|
| Host | Hetzner Cloud, Ubuntu 24.04 |
| SSH user | `stockup` |
| Public IP | `2.28.75.21` |
| SSH key | `C:\Users\JOEL\.ssh\id_ed25519` (see § 0b below) |
| Repo paths on VM | `~/proxy/`, `~/apps/stockup/`, `~/apps/maliscope/`, `~/apps/pesatrack/` |
| StockUp env file | `~/apps/stockup/.env` (literal `.env`, **not** `.env.production`) |

Ready-to-paste shell:

```powershell
ssh stockup@2.28.75.21
```

Because the app is now served publicly at `https://stockup.jmumo.com`, no SSH
tunnel is needed for normal use. Only tunnel when debugging Postgres or Redis
directly (see § 5).

## 0. Prep your laptop

### 0a. Azure VM (legacy) — lock down the `.pem`

The `.pem` you downloaded from Azure is your SSH key. Lock its permissions:

```powershell
icacls StockUpVM_key.pem /inheritance:r
icacls StockUpVM_key.pem /grant:r "$($env:USERNAME):(R)"
```

### 0b. Hetzner (and any new host) — generate a keypair

Hetzner (unlike Azure) doesn't hand you a `.pem`; you upload your **public key** when
creating the server and keep the **private key** on your laptop. Do this once — the
same key is reused for every future server.

| Field | Value |
|---|---|
| Key type | `ed25519` |
| Private key | `C:\Users\JOEL\.ssh\id_ed25519` |
| Public key | `C:\Users\JOEL\.ssh\id_ed25519.pub` (paste this into Hetzner) |
| Passphrase | none (matches the current Azure `.pem` workflow) |

Generate (only if the file above doesn't already exist — check with
`Test-Path $env:USERPROFILE\.ssh\id_ed25519`):

```powershell
ssh-keygen -t ed25519 -C "stockup-hetzner" -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""'
```

Show the public key so you can paste it into the Hetzner console:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

Because the key lives at the default path, `ssh` finds it automatically — **no `-i`
flag needed**:

```powershell
ssh root@<hetzner-ip>              # first login (Hetzner default user)
ssh stockup@<hetzner-ip>            # after you create the stockup user
```

**Back it up.** If `C:\Users\JOEL\.ssh\id_ed25519` is lost, you're locked out of every
server that trusts it. Copy the whole `.ssh` folder to a password manager or an
encrypted USB stick.

---

## 1. First-time host bootstrap

### 1a. Create the Hetzner server

1. Hetzner Cloud console → **Add Server**.
2. Location: Falkenstein or Nuremberg.
3. Image: **Ubuntu 24.04**.
4. Type: **CPX21** (3 vCPU AMD, 4 GB RAM, 80 GB disk).
5. **SSH keys**: upload the pubkey from § 0b.
6. **Firewall**: attach a Hetzner Cloud Firewall with three inbound TCP rules — single ports `22`, `80`, `443`. Source `0.0.0.0/0, ::/0` (or lock `22` to your home IP).
7. Note the **IPv4** address.

### 1b. Point DNS at the server

At the registrar hosting `jmumo.com`, add:

| Type | Name | Value | TTL |
|---|---|---|---|
| `A` | `stockup` | `<hetzner-ip>` | 300 |
| `A` | `maliscope` | `<hetzner-ip>` | 300 |
| `A` | `pesatrack` | `<hetzner-ip>` | 300 |

(Or a single wildcard `*` → `<hetzner-ip>` if the registrar allows it. Then
adding future apps is just a Caddyfile edit.)

Verify:

```powershell
nslookup stockup.jmumo.com
```

Let's Encrypt refuses to issue certs until DNS resolves to the Hetzner IP.

### 1c. Harden the server + install Docker

SSH in as `root` (Hetzner default):

```powershell
ssh root@<hetzner-ip>
```

Create the app user and lock down SSH:

```bash
adduser --disabled-password --gecos "" stockup
usermod -aG sudo stockup
mkdir -p /home/stockup/.ssh
cp ~/.ssh/authorized_keys /home/stockup/.ssh/
chown -R stockup:stockup /home/stockup/.ssh
chmod 700 /home/stockup/.ssh && chmod 600 /home/stockup/.ssh/authorized_keys

sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

exit
```

Reconnect as `stockup` and run the bootstrap script. It installs Docker, UFW, and
unattended security upgrades:

```powershell
ssh stockup@<hetzner-ip>
```

```bash
git clone https://github.com/<you>/stockup.git ~/tmp-stockup   # scratch clone just for setup-vm.sh
bash ~/tmp-stockup/deploy/setup-vm.sh
rm -rf ~/tmp-stockup
exit    # re-login so the docker group applies
```

Reconnect and open the web ports on UFW (script only allows SSH):

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

### 1d. Lay out the directories

```bash
mkdir -p ~/apps ~/backups
```

---

## 2. Deploy the shared proxy (once per host)

```bash
# One-time: create the shared Docker network. Every app declares it as external.
docker network create web

# Clone StockUp into ~/apps/stockup so we can copy the proxy templates from it
git clone https://github.com/<you>/stockup.git ~/apps/stockup

# Copy the proxy stack to ~/proxy
mkdir -p ~/proxy
cp ~/apps/stockup/deploy/proxy/docker-compose.yml ~/proxy/
cp ~/apps/stockup/deploy/proxy/Caddyfile          ~/proxy/

# Bring the proxy up
cd ~/proxy && docker compose up -d
docker compose logs -f caddy    # watch first-boot ACME
```

After edits to `~/proxy/Caddyfile`, reload without downtime:

```bash
cd ~/proxy
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

See [deploy/proxy/README.md](proxy/README.md) for the "add a new app" checklist.

---

## 3. Deploy StockUp

```bash
cd ~/apps/stockup
cp .env.production.example .env
nano .env
# Set at minimum:
#   POSTGRES_PASSWORD   (openssl rand -hex 24)
#   JWT_SECRET_KEY      (openssl rand -hex 48)
#   OPENAI_API_KEY
#   CORS_ORIGINS=https://stockup.jmumo.com
```

The stack expects the external `web` network to exist (Step 2). Build and start:

```bash
docker compose up -d --build
docker compose logs -f api worker beat
```

Migrations run automatically on `api` startup (`alembic upgrade head`).

> The file **must** be named `.env` (not `.env.production`). Compose only auto-loads
> the literal name `.env` for `ps` / `logs` / `exec`. Symlink if needed:
> `ln -s .env.production .env`.

Once the containers are healthy, `https://stockup.jmumo.com` should serve the SPA
and `https://stockup.jmumo.com/api/docs` the FastAPI OpenAPI page. Caddy provisions
the Let's Encrypt cert on the first HTTPS request.

### 3a. Seed and backfill

```bash
docker compose exec api python -m cli.commands seed-nse
docker compose exec api python -m cli.commands backfill-prices
```

Celery beat then keeps things fresh on the daily schedule in
[backend/tasks/celery_app.py](../backend/tasks/celery_app.py).

---

## 4. Deploy another app (MaliScope, PesaTrack, ...)

Same pattern as StockUp — the app owns its stack; the proxy owns TLS/routing.

1. Clone the app: `git clone <repo> ~/apps/<name>`.
2. Make sure the app has a `Dockerfile` for its public service and a `docker-compose.yml` that:
   - Names the project (`name: <name>`), so containers become `<name>-web-1`.
   - Puts the public service on the external `web` network:
     ```yaml
     services:
       web:
         # ...
         networks: [default, web]
     networks:
       default:
       web:
         external: true
     ```
3. Add a Caddyfile block in `~/proxy/Caddyfile`:
   ```caddy
   maliscope.jmumo.com {
       encode zstd gzip
       reverse_proxy maliscope-web-1:3000
   }
   ```
4. Reload the proxy and bring the app up:
   ```bash
   cd ~/proxy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
   cd ~/apps/maliscope && docker compose up -d --build
   ```

The Caddyfile shipped in [deploy/proxy/Caddyfile](proxy/Caddyfile) already contains
commented placeholders for `maliscope.jmumo.com` and `pesatrack.jmumo.com`.

---

## 5. Day-to-day commands

### Update after `git push`

```bash
# StockUp
cd ~/apps/stockup && git pull && docker compose up -d --build
# MaliScope
cd ~/apps/maliscope && git pull && docker compose up -d --build
# Proxy config change
cd ~/proxy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

The legacy `stockup-update` alias installed by `setup-vm.sh` still works when
`STOCKUP_DIR=~/apps/stockup` is set.

### One-off shells / logs

```bash
docker compose exec api bash                # StockUp API shell
docker compose logs -f api worker beat      # StockUp logs
docker compose restart worker               # restart one service
```

### Optional: SSH tunnel to Postgres / Redis

The app databases don't publish host ports. For direct pgAdmin access, add a
temporary `ports: ["127.0.0.1:5432:5432"]` line under the `postgres` service,
`docker compose up -d postgres`, tunnel from your laptop with
`ssh -L 5432:localhost:5432 stockup@<hetzner-ip>`, then remove the port when
done.

### Stop / wipe

```bash
docker compose down          # stop, keep data (volumes persist)
docker compose down -v       # stop + WIPE all named volumes for the project (DESTRUCTIVE)
```

---

## 6. Backups

Nightly per-app Postgres dumps to `~/backups/<app>/`, rotate weekly. Add to
`crontab -e`:

```cron
# StockUp
0 2 * * * cd /home/stockup/apps/stockup && docker compose exec -T postgres \
  pg_dump -U stockup stockup | gzip > /home/stockup/backups/stockup/stockup-$(date +\%Y\%m\%d).sql.gz \
  && find /home/stockup/backups/stockup -name 'stockup-*.sql.gz' -mtime +7 -delete

# MaliScope (uncomment when deployed)
# 15 2 * * * cd /home/stockup/apps/maliscope && docker compose exec -T postgres \
#   pg_dump -U maliscope maliscope | gzip > /home/stockup/backups/maliscope/maliscope-$(date +\%Y\%m\%d).sql.gz \
#   && find /home/stockup/backups/maliscope -name 'maliscope-*.sql.gz' -mtime +7 -delete
```

`mkdir -p ~/backups/stockup` first. For off-host backup, push the latest dump to
Backblaze B2 or a Hetzner Storage Box from the same cron.

---

## 7. Migrating / restoring Postgres data

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
scp stockup.dump stockup@<hetzner-ip>:~/stockup.dump
```

### Import into the VM's container

```bash
cd ~/apps/stockup

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

---

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

Docker Compose only auto-loads a file literally named `.env`. Make sure your
production env file is named `.env` (not `.env.production`):

```bash
mv .env.production .env      # or:  ln -s .env.production .env
```

### `network web declared as external, but could not be found`

The shared network hasn't been created on this host yet. Once, as the `stockup`
user:

```bash
docker network create web
```

### Caddy stuck on `challenge failed` / `no certificate found`

- DNS doesn't yet resolve to this host, OR
- UFW / Hetzner Cloud Firewall isn't forwarding port 80 (Let's Encrypt's HTTP-01
  challenge needs it, not just 443).

Fix DNS first, wait for propagation (`nslookup stockup.jmumo.com`), then:

```bash
cd ~/proxy && docker compose restart caddy
```

### Frontend `npm run dev` shows proxy errors

The Vite dev server proxies `/api/*` to `http://localhost:8000`. For local dev,
run the backend locally (`uvicorn app.main:app --reload`) — do NOT point at the
production API from `npm run dev`, or you'll pollute prod state.

### Generating random secrets on Windows (no OpenSSL)

`openssl rand -hex 24` doesn't ship with PowerShell. Either run it on the VM,
or use this PowerShell substitute:

```powershell
# 48 hex chars (good for POSTGRES_PASSWORD)
-join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })

# 96 hex chars (good for JWT_SECRET_KEY)
-join ((1..96) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
```

---

## Appendix A. Legacy Azure VM

The previous single-app deployment ran on Azure at `stockup@102.37.15.86` with the
API bound to `127.0.0.1:8000` and accessed via SSH tunnel:

```powershell
ssh -i C:\Users\JOEL\Downloads\StockUpVM_key.pem -L 8000:localhost:8000 stockup@102.37.15.86
```

That layout is superseded by the Hetzner multi-app setup above. Migration
checklist:

1. Take a fresh `pg_dump` on the Azure VM (§ 7).
2. `scp` it to your laptop, then to the Hetzner host.
3. Bring StockUp up on Hetzner, restore the dump (§ 7).
4. Point `stockup.jmumo.com` at the Hetzner IP.
5. Stop or delete the Azure VM.

Cost note: Azure charges the OS disk (~$2.40/mo) while the VM is **Deallocated**.
Delete the resource group to stop billing entirely.
