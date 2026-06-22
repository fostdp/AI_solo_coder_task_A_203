#!/usr/bin/env bash
# ============================================================
#  InfluxDB 初始化脚本 — 降采样与连续查询
#  在 InfluxDB 容器首次启动时通过 entrypoint 执行
# ============================================================
set -e

echo "[influxdb-init] Waiting for InfluxDB to be ready..."
until curl -fsS http://localhost:8086/health > /dev/null 2>&1; do
  sleep 2
done
sleep 3
echo "[influxdb-init] InfluxDB is ready."

INFLUX_TOKEN="${DOCKER_INFLUXDB_INIT_ADMIN_TOKEN}"
INFLUX_ORG="${DOCKER_INFLUXDB_INIT_ORG}"
INFLUX_BUCKET="${DOCKER_INFLUXDB_INIT_BUCKET}"
DOWNSAMPLE_BUCKET="${INFLUX_BUCKET}_downsampled_1m"

echo "[influxdb-init] Using org=${INFLUX_ORG} bucket=${INFLUX_BUCKET}"

# ---------- 1. 创建降采样桶 ----------
echo "[influxdb-init] Creating downsample bucket: ${DOWNSAMPLE_BUCKET} (retention 30d)"
influx bucket create \
  --name "${DOWNSAMPLE_BUCKET}" \
  --org "${INFLUX_ORG}" \
  --retention 720h \
  --token "${INFLUX_TOKEN}" 2>/dev/null || true

# ---------- 2. 查询桶 ID ----------
SRC_ID=$(influx bucket list --name "${INFLUX_BUCKET}" --org "${INFLUX_ORG}" --token "${INFLUX_TOKEN}" | awk 'NR==2 {print $1}')
DST_ID=$(influx bucket list --name "${DOWNSAMPLE_BUCKET}" --org "${INFLUX_ORG}" --token "${INFLUX_TOKEN}" | awk 'NR==2 {print $1}')
echo "[influxdb-init] Source bucket id: ${SRC_ID}"
echo "[influxdb-init] Downsample bucket id: ${DST_ID}"

# ---------- 3. 创建 Task: 每 1 分钟对 raw bucket 做 mean/median/max/min 聚合 ----------
TASK_FLUX=$(cat <<EOF
option task = {name: "bearing_downsample_1m", every: 1m}

data = from(bucket: "${INFLUX_BUCKET}")
  |> range(start: -1m, stop: now())
  |> filter(fn: (r) => r._measurement == "bearing_sensor")
  |> drop(columns: ["_start", "_stop"])

agg = data
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> set(key: "_agg", value: "mean")

max = data
  |> aggregateWindow(every: 1m, fn: max, createEmpty: false)
  |> set(key: "_agg", value: "max")

min = data
  |> aggregateWindow(every: 1m, fn: min, createEmpty: false)
  |> set(key: "_agg", value: "min")

union(tables: [agg, max, min])
  |> to(bucketID: "${DST_ID}", org: "${INFLUX_ORG}")
EOF
)

echo "[influxdb-init] Creating downsample task..."
influx task create \
  --org "${INFLUX_ORG}" \
  --token "${INFLUX_TOKEN}" \
  --name "bearing_downsample_1m" \
  --every 1m \
  --flux "${TASK_FLUX}" 2>/dev/null || echo "[influxdb-init] Task may already exist, skipping."

echo "[influxdb-init] Done."
