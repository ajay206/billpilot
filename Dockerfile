FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/ajay206/billpilot" \
      org.opencontainers.image.url="https://github.com/ajay206/billpilot" \
      org.opencontainers.image.title="BillPilot" \
      org.opencontainers.image.description="Phase 1 mock BSS for BillPilot: synthetic telecom billing data and TMF-shaped APIs."

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
RUN pip install --no-cache-dir .

COPY scripts ./scripts
EXPOSE 8000
CMD ["sh", "scripts/serve.sh"]
