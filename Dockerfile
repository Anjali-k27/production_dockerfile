# ============================================================
# epoch-gateway — production image
# Stage 1: builder — compiles dependencies, never shipped
# Stage 2: runtime — copies only what runs
# ============================================================

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim AS runtime

WORKDIR /app

# --- curl: the only runtime OS package, used by HEALTHCHECK (no compilers here) ---
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# --- install compiled wheels only, no compiler in this stage ---
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# --- non-root user, UID 1000 ---
RUN groupadd -g 1000 epoch && \
    useradd -u 1000 -g epoch -s /bin/bash -m epoch

COPY epoch_gateway/ ./epoch_gateway/
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/healthcheck.sh && \
    chown -R epoch:epoch /app

USER epoch

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["/usr/local/bin/healthcheck.sh"]

CMD ["uvicorn", "epoch_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
