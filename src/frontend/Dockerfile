# =============================================================================
# STAGE 1: deps — instala dependências em camada cacheável
# =============================================================================
FROM node:20-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# =============================================================================
# STAGE 2: builder — compila o Next.js em modo standalone
# =============================================================================
FROM node:20-alpine AS builder

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# =============================================================================
# STAGE 3: runner — imagem final mínima, non-root
# =============================================================================
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 farol

COPY --from=builder --chown=farol:nodejs /app/.next/standalone ./
COPY --from=builder --chown=farol:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=farol:nodejs /app/public ./public

USER farol

EXPOSE 3000
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

CMD ["node", "server.js"]
