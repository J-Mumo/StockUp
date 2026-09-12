# Local price updater setup

Marketscreener's Akamai bot protection blocks the production Hetzner VM (HTTP 403),
so daily NSE prices are ingested from a residential IP via a local scheduled task.

## One-time setup

1. Pick a strong shared secret and add it in **both** places:

   **Server** — `~/apps/stockup/.env` on the VM, then restart the api container:
   ```
   INTERNAL_API_TOKEN=<some-long-random-string>
   ```
   ```powershell
   ssh stockup@2.28.75.21 'cd ~/apps/stockup && docker compose up -d --no-deps api'
   ```

   **Local** — `backend/scripts/.env` (this directory) — NEVER commit:
   ```
   STOCKUP_API_BASE=https://stockup.jmumo.com
   INTERNAL_API_TOKEN=<same-long-random-string>
   ```

2. From the repo root with the backend venv active, verify with a dry-run:
   ```powershell
   cd C:\Eng\StockUp\backend
   .\venv\Scripts\python.exe -m scripts.local_price_updater --ticker SCOM --days 14 --dry-run
   ```
   Expect: fetches SCOM history, prints latest close.

3. Real run (posts to server):
   ```powershell
   .\venv\Scripts\python.exe -m scripts.local_price_updater --days 14
   ```

## Windows Task Scheduler (daily)

Create a Basic Task:

- **Trigger**: Daily at 6:30 PM local time
- **Action** → Start a program:
  - Program: `C:\Eng\StockUp\backend\venv\Scripts\python.exe`
  - Arguments: `-m scripts.local_price_updater --days 14`
  - Start in: `C:\Eng\StockUp\backend`
- **Conditions**: uncheck "Start only if on AC power"; check "Wake computer to run this task" if you want it to run when the PC is asleep.

Or via PowerShell (adjust the trigger time as needed):
```powershell
$action  = New-ScheduledTaskAction `
    -Execute "C:\Eng\StockUp\backend\venv\Scripts\python.exe" `
    -Argument "-m scripts.local_price_updater --days 14" `
    -WorkingDirectory "C:\Eng\StockUp\backend"
$trigger = New-ScheduledTaskTrigger -Daily -At 6:30PM
Register-ScheduledTask -TaskName "StockUp Daily Prices" -Action $action -Trigger $trigger -RunLevel Highest
```

## Notes

- Full run takes ~15–20 min (60 companies × ~15s each via Playwright Firefox).
- Uses idempotent upsert — safe to run multiple times per day; will backfill any gap.
- If you miss a few days, bump `--days` to cover the gap (e.g. `--days 30`).
- Server-side Celery `daily-price-fetch` schedule is intentionally commented out
  in [backend/tasks/celery_app.py](../tasks/celery_app.py) — do not re-enable
  unless a working server-side data source is added.
