# ── Stage 1: Build ────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY ui/package.json ui/tsconfig.json ui/vite.config.ts ./
RUN npm install --frozen-lockfile 2>/dev/null || npm install

COPY ui/ ./
RUN npm run build

# ── Stage 2: Serve ───────────────────────────────────────
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# SPA fallback
RUN echo 'server { \
    listen 80; \
    root /usr/share/nginx/html; \
    location / { try_files $uri $uri/ /index.html; } \
    location /api/ { proxy_pass http://poi-backend:8000; } \
    location /ws/ { proxy_pass http://poi-backend:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
