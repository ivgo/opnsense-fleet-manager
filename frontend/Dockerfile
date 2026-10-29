# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install --no-audit --no-fund; fi

COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src

ARG VITE_API_BASE_URL=""
ARG VITE_WS_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_BASE_URL=$VITE_WS_BASE_URL

RUN npm run build


FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/* \
    && addgroup -S -g 10002 ofme \
    && adduser -S -D -H -u 10002 -G ofme ofme \
    && chown -R ofme:ofme /var/cache/nginx /var/run /usr/share/nginx/html

COPY nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

USER ofme
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
