# Shared reverse proxy for jmumo.com apps

Runs one Caddy container that terminates TLS for every app hosted on this
Hetzner box and routes to per-app containers over an external Docker network.

## First-time setup on the host

```bash
# 1) One-time: create the shared network. Every app also declares this network
#    as `external: true` in its own compose file.
docker network create web

# 2) Copy this folder to ~/proxy on the host.
mkdir -p ~/proxy
cp docker-compose.yml Caddyfile ~/proxy/

# 3) Bring the proxy up.
cd ~/proxy
docker compose up -d
docker compose logs -f caddy    # watch first-boot ACME
```

Once DNS for a hostname points at this host, Caddy provisions a Let's Encrypt
cert automatically on the first HTTPS request.

## Adding a new app

1. Give the app a `docker-compose.yml` where at least one service is on the
   external `web` network:

   ```yaml
   services:
     web:
       # ...
       networks:
         - default
         - web
   networks:
     default:
     web:
       external: true
   ```

2. Add a site block to `~/proxy/Caddyfile` pointing at the container name
   (`<project>-<service>-<index>`), e.g.:

   ```caddy
   app.jmumo.com {
       reverse_proxy myapp-web-1:3000
   }
   ```

3. Reload (no downtime):

   ```bash
   cd ~/proxy
   docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

4. Bring the app up:

   ```bash
   cd ~/apps/myapp && docker compose up -d --build
   ```

5. Add the DNS `A` record (skip if you have a wildcard `*.jmumo.com`).

## Files

- [docker-compose.yml](docker-compose.yml) — Caddy container, ports 80/443, joined to the external `web` network.
- [Caddyfile](Caddyfile) — one site block per hostname. Edit and reload.
