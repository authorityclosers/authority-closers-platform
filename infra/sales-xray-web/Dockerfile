# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df

FROM ${NODE_IMAGE} AS build

ARG AC_RELEASE_ID
ENV AC_RELEASE_ID=${AC_RELEASE_ID} \
    NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"

WORKDIR /workspace

RUN corepack enable && corepack prepare pnpm@11.19.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/sales-xray-web/package.json apps/sales-xray-web/package.json
COPY packages/typescript/config/package.json packages/typescript/config/package.json
COPY packages/typescript/sales-xray-client/package.json packages/typescript/sales-xray-client/package.json
COPY packages/typescript/ui/package.json packages/typescript/ui/package.json

RUN --mount=type=cache,id=ac-pnpm-store,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store && \
    pnpm config set fetch-timeout 300000 && \
    pnpm install \
      --frozen-lockfile \
      --network-concurrency 8 \
      --prefer-offline \
      --trust-lockfile

COPY apps/sales-xray-web apps/sales-xray-web
COPY packages/typescript packages/typescript

RUN pnpm --filter @ac/sales-xray-web build

FROM ${NODE_IMAGE} AS runtime

ARG AC_RELEASE_ID
ENV AC_RELEASE_ID=${AC_RELEASE_ID} \
    HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3016
LABEL org.opencontainers.image.revision=${AC_RELEASE_ID}

WORKDIR /app

COPY --from=build --chown=node:node /workspace/apps/sales-xray-web/.next/standalone ./
COPY --from=build --chown=node:node \
    /workspace/apps/sales-xray-web/.next/static \
    ./apps/sales-xray-web/.next/static
COPY --from=build --chown=node:node \
    /workspace/apps/sales-xray-web/public \
    ./apps/sales-xray-web/public

RUN test -n "$AC_RELEASE_ID" && \
    printf '%s\n' "$AC_RELEASE_ID" > /app/.ac-release-id && \
    chown node:node /app/.ac-release-id && \
    chmod 0444 /app/.ac-release-id

USER node
EXPOSE 3016
CMD ["node", "apps/sales-xray-web/server.js"]
