#!/usr/bin/env bash
set -e

SERVICE_ROLE=${SERVICE_ROLE:-fastapi}
PYTHONPATH=${PYTHONPATH:-/app}
export PYTHONPATH

cd /app

echo "[entrypoint] SERVICE_ROLE=${SERVICE_ROLE}"
echo "[entrypoint] PYTHONPATH=${PYTHONPATH}"

case "${SERVICE_ROLE}" in
  fastapi)
    WORKERS=${GUNICORN_WORKERS:-4}
    PORT=${GUNICORN_PORT:-8000}
    echo "[entrypoint] Starting FastAPI: gunicorn workers=${WORKERS} port=${PORT}"
    exec gunicorn backend.main:app \
      --config /app/docker/gunicorn_conf.py \
      --workers "${WORKERS}" \
      --bind "0.0.0.0:${PORT}"
    ;;

  simulator)
    echo "[entrypoint] Starting BearingSimulator"
    exec python -u /app/backend/simulator.py
    ;;

  worker)
    # 预留：可作为独立worker单独跑某一个微服务
    WORKER_NAME=${WORKER_NAME:-flow_simulator}
    echo "[entrypoint] Starting worker: ${WORKER_NAME}"
    exec python -u -m "backend.services.${WORKER_NAME}"
    ;;

  *)
    echo "[entrypoint] Unknown SERVICE_ROLE=${SERVICE_ROLE}, executing custom command"
    exec "$@"
    ;;
esac
