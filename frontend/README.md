# frontend

React single-page application (Vite + TypeScript). The app builds to static
assets that nginx serves in both local and production environments. nginx is the
**sole public entry point**: it serves the SPA and reverse-proxies `/api/`
requests to the `core` FastAPI service.

## How it is built and served

`Dockerfile` is a **multi-stage build**:

1. `node:20-alpine` runs `npm ci` and `npm run build`, producing `dist/`.
2. `nginx:1.27-alpine` copies `dist/` into `/usr/share/nginx/html` and the
   `nginx.conf` into `/etc/nginx/conf.d/default.conf`.

The result is one immutable `policyflow-frontend` image — the static assets are
**baked into the nginx image** (no shared volume). `nginx.conf` adds an SPA
fallback (`try_files … /index.html`) so client routes resolve to the app, and a
`/api/` reverse proxy to `http://core:8000`.

## Local development

The default `docker compose up --build` runs the exact prod-parity path (nginx
serving the build) at `http://localhost/`. **The Vite dev server is deferred**
for now — the `docker-compose.override.yml` that `docker compose up` auto-loads
only publishes the RabbitMQ management UI port and provides no frontend hot-reload.
To see frontend changes, rebuild the image (`docker compose up -d --build frontend`).
Hot reload will be added when real frontend churn arrives (Epic 5 / P1.6).

For a quick local-only build outside Docker: `npm install` then `npm run build`
produces `dist/`.
