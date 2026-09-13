# Frontend production image — Next.js standalone output.
#
# Not used by backend/docker-compose.yml (local dev runs `npm run dev` on
# :3100 directly); this exists for the deployed stack, where
# backend/docker-compose.prod.yml builds it with context ../frontend.
FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# ─────────────────────────────────────────────────────────────────────
# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, not read
# from the environment at runtime. If this arg is missing the image still
# builds and starts cleanly, then every browser request goes to whatever
# the fallback in src/lib/api.ts is — which looks like a backend outage,
# not a build misconfiguration. Keep it wired to the compose build args.
# ─────────────────────────────────────────────────────────────────────
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN groupadd -g 1001 nodejs && useradd -u 1001 -g nodejs -m nextjs

# standalone/ carries its own minimal node_modules and server.js; static/
# must be copied alongside it because Next deliberately leaves it out.
# There is no public/ directory in this project — do not add a COPY for it
# without creating the directory first, or the build fails here.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

# HOSTNAME must be 0.0.0.0: the standalone server binds localhost by
# default, which is unreachable from outside the container.
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
EXPOSE 3000

CMD ["node", "server.js"]
