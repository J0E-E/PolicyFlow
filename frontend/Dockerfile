# Multi-stage build: stage 1 builds the Vite SPA, stage 2 bakes the static
# assets into an nginx runtime image. One immutable policyflow-frontend image
# serves the SPA and reverse-proxies /api/ to core (nginx is the sole entry).

# --- Stage 1: build the static assets ---
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- Stage 2: nginx runtime serving the build ---
FROM nginx:1.27-alpine AS runtime

# wget (in busybox) is used by the docker-compose container health check.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
