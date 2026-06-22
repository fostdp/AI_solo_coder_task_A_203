# ============================================================
#  Stage 1 — Builder: 安装编译依赖，构建所有 wheel
# ============================================================
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        gfortran \
        libopenblas-dev \
        liblapack-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ============================================================
#  Stage 2 — Runtime: 仅复制运行时依赖，镜像最小化
# ============================================================
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app \
    TZ=Asia/Shanghai

# 仅安装运行时需要的系统库（OpenBLAS供numpy/scipy使用）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libopenblas0 \
        libgomp1 \
        tzdata \
        curl \
    && ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR ${APP_HOME}

# 从 builder 复制预编译好的 wheels
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

# 复制应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY config/ ./config/ 2>/dev/null || true

# 入口脚本：根据 SERVICE_ROLE 启动不同服务
COPY docker/entrypoint.sh ./docker/entrypoint.sh
COPY docker/gunicorn_conf.py ./docker/gunicorn_conf.py

RUN chmod +x ./docker/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["./docker/entrypoint.sh"]
