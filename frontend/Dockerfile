# Multi-stage build for the Vite/React SPA.
#
# Stage 1 — install deps and produce the static `dist/` bundle.
# Stage 2 — serve `dist/` with a tiny Caddy container on port 80.
#
# Consumed by the top-level docker-compose.yml. TLS is terminated upstream by
# the shared Caddy proxy stack at ~/proxy on the host; this Caddy just serves
# static assets over plain HTTP inside the Docker network.

FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM caddy:2-alpine AS runtime
COPY --from=build /app/dist /usr/share/caddy
COPY Caddyfile /etc/caddy/Caddyfile
# SPA fallback ensures react-router routes survive a hard refresh.
