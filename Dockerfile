FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ajay206/billpilot" \
      org.opencontainers.image.url="https://github.com/ajay206/billpilot" \
      org.opencontainers.image.title="BillPilot" \
      org.opencontainers.image.description="BillPilot mock BSS, billing copilot, and persona UI. Synthetic data only."

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY docs/knowledge ./docs/knowledge
RUN pip install --no-cache-dir .

COPY scripts ./scripts
COPY --from=web /web/dist ./web/dist
EXPOSE 8000
CMD ["sh", "scripts/serve.sh"]
