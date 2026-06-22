"""Gunicorn 配置 — FastAPI 生产部署"""

import multiprocessing
import os

# ---------- Worker ----------
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 5000
max_requests_jitter = 500
timeout = 120
graceful_timeout = 30
keepalive = 5

# ---------- Server ----------
bind = "0.0.0.0:8000"
backlog = 2048

# ---------- Logging ----------
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'

# ---------- Process ----------
preload_app = True
daemon = False

# ---------- Uvicorn extras (传递给 worker) ----------
raw_env = [
    "UVICORN_PROTOCOL=h11",
]


def when_ready(server):
    server.log.info("Gunicorn + Uvicorn ready. workers=%s class=%s",
                    server.num_workers, worker_class)
