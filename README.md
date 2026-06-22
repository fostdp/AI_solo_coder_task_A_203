# 古代筒车轴承水润滑流场仿真与摩擦功耗分析系统

> 宋代筒车水润滑轴承研究平台 v3.0（工程化版）

面向水利史研究团队提供的一套水润滑轴承流场仿真系统，包含：
- **后端四微服务**：DTU 数据采集、NS+空化、摩擦+温升、告警推送
- **前端三维可视化**：Three.js 轴承渲染 + SPH 水膜粒子 + 实时图表
- **工程化**：Docker 多阶段构建 + docker-compose 一键编排 + gunicorn/uvicorn 生产部署 + InfluxDB 降采样

---

## 一、系统架构

### 1.1 总体架构图

```mermaid
flowchart LR
    subgraph 外部设备 / 仿真器
        DTU[DTU 采集终端]
        SIM[水润滑轴承模拟器]
    end

    subgraph 数据接入
        MQTT[Eclipse Mosquitto<br/>MQTT Broker :1883]
    end

    subgraph 后端微服务编排层
        API[FastAPI<br/>gunicorn + uvicorn<br/>:8000]
        BUS[(Redis Pub/Sub :6379)]
    end

    subgraph 微服务（可独立部署）
        DTU_SVC[dtu_receiver<br/>数据采集+校验]
        FLOW_SVC[flow_simulator<br/>雷诺方程+RP气泡]
        FRI_SVC[friction_analyzer<br/>粘温+温升迭代]
        ALARM_SVC[alarm_ws<br/>告警判定+WebSocket]
    end

    subgraph 时序存储
        TSDB[(InfluxDB v2 :8086<br/>bearing_sensor<br/>原始桶 + 降采样桶)]
    end

    subgraph 前端
        UI[浏览器<br/>index.html + Gzip]
        THREE[[water_bearing_3d.js<br/>轴承三维渲染]
        PANEL[[flow_panel.js<br/>SPH粒子+图表]]
        WS[/WebSocket 告警]
    end

    %% 数据流
    DTU --> MQTT
    SIM -->|REST / Redis Pub/Sub| API
    MQTT -->|桥接| API
    API --> DTU_SVC
    DTU_SVC -->|raw_data| BUS
    BUS -->|raw_data| FLOW_SVC
    FLOW_SVC -->|flow_result| BUS
    BUS -->|flow_result| FRI_SVC
    FRI_SVC -->|friction_result| BUS
    BUS -->|flow_result / friction_result| ALARM_SVC
    DTU_SVC --> TSDB
    ALARM_SVC -->|/ws| WS
    UI --> THREE
    UI --> PANEL
    UI -->|HTTP| API
```

### 1.2 模块说明

| 模块 | 职责 | 关键技术 |
| 通讯方式 |
|---|---|---|---|
| `dtu_receiver` | DTU 数据采集、Pydantic 校验、InfluxDB 持久化、原始数据发布 | FastAPI + Pydantic + InfluxDB v2 | Redis Pub/Sub `bearing:raw_data` |
| `flow_simulator` | 雷诺方程 SOR 迭代求解、Rayleigh-Plesset 气泡动力学、水膜破裂风险评估 | NumPy + RP-RK4 积分 | 订阅 `raw_data`，发布 `flow_result` |
| `friction_analyzer` | 5 种粘温模型 (Andrade/Reynolds/Walther/Vogel/Polynomial)、温升-功率耦合迭代、换热评估 | NumPy | 订阅 `flow_result`，发布 `friction_result` |
| `alarm_ws` | 多阈值告警判定（空化/水膜破裂/功耗过载/温升过高）、WebSocket 广播、历史告警缓存 | Starlette WebSocket | 订阅 `flow_result`/friction_result`，`/ws` 端点 |

### 1.3 数据链路

```
DTU/模拟器
  → dtu_receiver (数据校验+存储)
    → flow_simulator (雷诺方程+空化)
      → friction_analyzer (粘温+温升)
        → alarm_ws (告警+ WebSocket 推送)
前端
```

---

## 二、快速部署 (docker-compose)

### 2.1 环境要求

- Docker ≥ 24.0+
- Docker Compose v2.20+
- 至少 4 GB 可用内存（物理仿真 NumPy + InfluxDB）

### 2.2 一键启动

```bash
# 1. 准备环境变量
cp .env.example .env
# 按需修改 .env，特别是 INFLUXDB_TOKEN 和 INFLUXDB_PASSWORD

# 2. 构建并启动全部服务
docker compose up -d --build

# 3. 查看日志
docker compose logs -f fastapi
docker compose logs -f simulator

# 4. 健康检查
curl http://localhost:8000/api/health
```

启动后的访问地址：

| 服务 | 地址 | 说明 |
|---|---|---|
| Web UI | http://localhost:8000/ | 前端监控大屏 |
| FastAPI API | http://localhost:8000/docs | Swagger 自动文档 |
| InfluxDB UI | http://localhost:8086 | 时序数据管理 |
| Redis | localhost:6379 | 消息总线 + 缓存 |
| MQTT Broker | localhost:1883 (MQTT)/ localhost:9001 (WS) | DTU 接入 |

### 2.3 停止与清理

```bash
# 停止
docker compose stop

# 停止并删除容器（保留数据卷）
docker compose down

# 完全清理（⚠️ 会删除数据卷）
docker compose down -v
```

---

## 三、模拟器 (BearingSimulator)

### 3.1 运行模式

模拟器有两种推送模式：

1. **消息总线模式（默认）：通过 Redis Pub/Sub 推送，经 dtu_receiver 校验、持久化、再发布
2. **REST 模式**：直接 HTTP POST 到 FastAPI

```bash
# docker-compose 中（已自动以消息总线模式启动）
# 通过环境变量控制。
```

### 3.2 可调参数（环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BEARING_ID` | `bearing-south-01` | 轴承唯一 ID |
| `SIM_BASE_RPM` | `30.0` | 基础转速（RPM） |
| `SIM_RPM_AMPLITUDE` | `8.0` | 转速波动幅值 |
| `SIM_BASE_TEMP_C` | `20.0` | 进水温度（摄氏度） |
| `SIM_WATER_QUALITY` | `clean` | 水质：`clean`/`sediment`/`salty`/`corrosive` |
| `SIM_LOAD_FACTOR` | `0.5` | 载荷系数，0~2 倍额定载荷 |
| `SIM_INTERVAL_SEC` | `5.0` | 推送间隔（秒） |
| `SIM_INJECT_FAULT` | `none` | 故障注入：`none`/`cavitation`/`wear`/`dry_run`/`overload` |

### 3.3 水质模型

| 水质 | 粘度修正 | 表面张力修正 | 磨粒浓度 | 典型场景 |
|---|---|---|---|---|
| `clean`     | ×1.00 | ×1.00 | 1.0e-7 / h | 清水实验 |
| `sediment`  | ×1.15 | ×0.95 | 5.0e-7 / h | 含沙河流 |
| `salty`     | ×1.08 | ×0.88 | 1.5e-7 / h | 河口/近海 |
| `corrosive` | ×0.95 | ×0.80 | 3.0e-6 / h | 工业废水 |

### 3.4 故障注入模型

| 故障 | 偏心偏移 | 转速下降 | 温升偏置 | 粘度放大 | 磨损加速 | 载荷放大 | 典型场景 |
|---|---|---|---|---|---|---|---|
| `none`       | 0.00 | 0 RPM | 0 K  | ×1.00 | ×1.0 | ×1.0 | 正常工况 |
| `cavitation` | 0.00 | 0 RPM | 5 K  | ×1.00 | ×1.5 | ×1.0 | 低压高转速 |
| `wear`       | 0.15 | 0 RPM | 3 K  | ×1.00 | ×8.0 | ×1.0 | 长期运行磨损 |
| `dry_run`    | 0.25 | 15 RPM| 20 K | ×3.50 | ×30  | ×1.0 | 断水干摩擦 |
| `overload`   | 0.05 | 5 RPM | 8 K  | ×1.00 | ×2.5 | ×1.8 | 超负荷 |

### 3.5 示例：模拟高转速+含沙水+空化故障

```bash
# 修改 docker-compose.yml 中 simulator 服务的环境变量
simulator:
  environment:
    SIM_BASE_RPM: 80.0
    SIM_RPM_AMPLITUDE: 20.0
    SIM_WATER_QUALITY: sediment
    SIM_INJECT_FAULT: cavitation
    SIM_BASE_TEMP_C: 25.0

# 重启模拟器
docker compose up -d simulator

# 观察告警
docker compose logs -f alarm_ws
```

### 3.6 本地运行模拟器（无 Docker）

```bash
python backend/simulator.py
# 或者带参数
SIM_BASE_RPM=60 SIM_WATER_QUALITY=corrosive SIM_INJECT_FAULT=wear python backend/simulator.py
```

---

## 四、生产部署细节

### 4.1 FastAPI 部署（Gunicorn + Uvicorn Workers

- **多 worker 多进程部署，推荐 worker 数 = CPU 核数
- **Gzip 压缩前端静态资源（≥512B 触发，等级 6）
- **CORS 全开（生产请限制 origin）
- **/api/health 健康检查供 docker HEALTHCHECK
- **max_requests=5000 自动回收 worker，防止内存泄漏

```bash
# 手动启动 gunicorn
gunicorn backend.main:app \
  --config docker/gunicorn_conf.py \
  --workers 4 \
  --bind 0.0.0.0:8000
```

### 4.2 InfluxDB 降采样

容器首次启动时自动执行：`docker/influxdb/init-downsampling.sh：

1. 创建降采样桶 `bearing_sensor_downsampled_1m`（保留 30 天
2. 每 1 分钟对 raw 桶做 mean/max/min 聚合
3. 原始桶默认保留 7 天（DOCKER_INFLUXDB_INIT_RETENTION=7d）

可以通过 InfluxDB UI（http://localhost:8086）查看 Tasks 和调整任务。

### 4.3 前端 Gzip 压缩

FastAPI 中间件对所有 ≥ 512 字节响应自动 Gzip 压缩（等级 6），包括：

- HTML / index.html
- JS（water_bearing_3d.js、flow_panel.js 等）
- CSS
- API 响应

浏览器端解压由浏览器自动处理。

### 4.4 配置文件外置

全部参数外置 JSON，无需改配置无需重新构建：

| 文件 | 说明 |
|---|---|
| [fluid_params.json] | 流体密度、粘度模型、表面张力、空化、SPH 参数 |
| [bearing_params.json] | 轴承几何、求解器参数、摩擦告警阈值、已知轴承列表 |
| [messaging.json] | Redis 通道名、Redis 连接、缓存 TTL |

修改后：

```bash
# 热加载（无需重启，调用 POST /api/config/reload
curl -X POST http://localhost:8000/api/config/reload
```

---

## 五、REST API 概览

| Method | Path | 说明 |
|---|---|---|
| GET | `/` | 前端首页 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/config/reload | 重载配置 |
| GET | `/api/bearings` | 已知轴承列表 |
| POST | `/api/bearing/{id}/data` | DTU 上报数据 |
| GET | `/api/bearing/{id}/latest` | 最新数据 |
| POST | `/api/bearing/{id}/history` | 历史查询 |
| POST | `/api/simulation/calculate` | 单次仿真计算 |
| GET | `/api/alerts` | 告警历史 |
| WS | `/ws` | WebSocket 告警推送 |

详细文档：http://localhost:8000/docs

---

## 六、前端模块

| 模块 | 文件 | 说明 |
|---|---|---|
| 三维渲染 | [water_bearing_3d.js] | Three.js 内外圈/水膜/水槽/水波动画，偏心/转速/水温/水压效果 |
| 粒子流场 | [flow_panel.js] | SPH 水膜粒子（Wendland C² 核/空间哈希/Couette 拖曳）+ Chart.js 功耗/温度双图 |

---

## 七、测试

```bash
# 架构回归测试（7 项：配置→总线→DTU→Flow→Friction→Alarm→E2E
python test_arch_regression.py

# 物理仿真测试
pytest test_simulation.py -v
```

---

## 八、故障排查

| 现象 | 可能原因 | 解决方法 |
|---|---|---|
| FastAPI 启动失败 | Redis 未就绪 | 查看日志 `docker compose logs fastapi` |
| 模拟器无数据推送 | Redis 连接失败或 BEARING_ID 冲突 | 检查 Redis 健康状态 `docker compose exec redis redis-cli ping` |
| 告警不触发 | 告警阈值过高 | 修改 [bearing_params.json] 中 `alarm` 节点 |
| InfluxDB 查询不到数据 | 桶名错误 | 检查 .env 中 INFLUXDB_BUCKET |
