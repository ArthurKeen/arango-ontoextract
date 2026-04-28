# ============================================================================
# Stage 1: Frontend dependencies
# ============================================================================
FROM node:20-alpine AS frontend-deps

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# ============================================================================
# Stage 2: Frontend build
# ============================================================================
FROM node:20-alpine AS frontend-build

WORKDIR /app

COPY --from=frontend-deps /app/node_modules ./node_modules
COPY frontend/ .

# Same-origin API behind nginx in unified image; override at build if needed (see Makefile).
ARG NEXT_PUBLIC_API_URL=/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build  # produces .next/standalone/

# ============================================================================
# Stage 3: Backend dependencies
# ============================================================================
FROM python:3.11-slim AS backend-build

WORKDIR /build

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install -e .

# ============================================================================
# Stage 4: Runtime
# ============================================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install curl for healthcheck, tini for PID 1, nginx for reverse proxy, and nodejs for frontend
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl tini nginx jq gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy Python app + installed packages
COPY --from=backend-build /install /usr/local
COPY backend/app/ ./app/
COPY backend/migrations/ ./migrations/

# Copy Next.js standalone output
COPY --from=frontend-build /app/.next/standalone ./frontend/
COPY --from=frontend-build /app/.next/static ./frontend/.next/static
COPY --from=frontend-build /app/public ./frontend/public

# Copy nginx configuration
COPY nginx/proxy.conf /etc/nginx/nginx.conf


# Copy entrypoint(s). Root `entrypoint` satisfies platforms that extract project.tar.gz
# and require a top-level entrypoint file; it delegates to the full startup script.
COPY scripts/docker/docker-entrypoint.sh /docker-entrypoint.sh
COPY entrypoint /entrypoint
RUN chmod +x /docker-entrypoint.sh /entrypoint

# Create non-root user
RUN groupadd -r aoe && useradd -r -g aoe aoe \
    && chown -R aoe:aoe /app \
    && mkdir -p /var/lib/nginx /var/log/nginx \
    && chown -R aoe:aoe /var/lib/nginx /var/log/nginx /etc/nginx

USER aoe

# Only expose 8000 (frontend + proxied backend)
EXPOSE 8000

ENV NODE_ENV=production
ENV HOSTNAME="0.0.0.0"

ENTRYPOINT ["/entrypoint"]
CMD []
