"""
古代筒车轴承水润滑流场仿真与摩擦功耗分析系统 - FastAPI编排层
职责: 对外暴露REST+WebSocket API，内部通过消息总线协调DTU/Flow/Friction/Alarm四服务。
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import get_bearing_config, get_nested, reload_all
from .database import InfluxDBClientWrapper
from .messaging import MessageBus
from .models.bearing import (
    Alert,
    BearingData,
    BearingDataReceived,
    BearingInfo,
    HistoryQuery,
    SimulationRequest,
    SimulationResponse,
)
from .services import (
    AlarmWebSocketService,
    DTUReceiver,
    FlowSimulator,
    FrictionAnalyzerService,
)

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
log = logging.getLogger(__name__)

app = FastAPI(
    title='Ancient Water Wheel Bearing Water Lubrication Simulation',
    description='宋代筒车水润滑轴承流场仿真与摩擦功耗分析系统 v3.0',
    version='3.0.0',
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# ---------- 依赖初始化 ----------
bus = MessageBus.instance()
db = InfluxDBClientWrapper()
dtu = DTUReceiver(bus=bus, db=db)
flow_sim = FlowSimulator(bus=bus)
friction_svc = FrictionAnalyzerService(bus=bus)
alarm_svc = AlarmWebSocketService(bus=bus)

KNOWN_BEARINGS_CFG = get_nested(get_bearing_config(), 'known_bearings', [])
KNOWN_BEARINGS = {b['id']: b for b in KNOWN_BEARINGS_CFG}

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
if os.path.isdir(FRONTEND_DIR):
    app.mount('/static', StaticFiles(directory=FRONTEND_DIR), name='static')


# ---------- 首页 ----------
@app.get('/', response_class=HTMLResponse, tags=['UI'])
async def root():
    index_path = os.path.join(FRONTEND_DIR, 'index.html')
    if os.path.isfile(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            return f.read()
    return HTMLResponse('<h1>轴承水润滑仿真系统 v3.0</h1><p>前端文件未部署。</p>')


@app.get('/api/health', tags=['System'])
async def health():
    return {
        'status': 'ok',
        'version': '3.0.0',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'message_bus': bus.mode,
        'influxdb': db.client is not None,
        'connections_ws': alarm_svc.manager.connection_count,
    }


@app.post('/api/config/reload', tags=['System'])
async def reload_config():
    reload_all()
    return {'status': 'reloaded'}


# ---------- 轴承元数据 ----------
@app.get('/api/bearings', response_model=List[BearingInfo], tags=['Bearing'])
async def list_bearings():
    out = []
    known = {b['id']: b for b in KNOWN_BEARINGS_CFG}
    for bid in dtu.list_recent_ids():
        known.setdefault(bid, {'id': bid, 'name': bid, 'location': 'unknown'})
    for bid, info in known.items():
        out.append(BearingInfo(
            id=info['id'],
            name=info.get('name', info['id']),
            location=info.get('location', ''),
            description=info.get('description', ''),
        ))
    return out


# ---------- 数据接收 (DTU) ----------
@app.post('/api/bearing/{bearing_id}/data', response_model=BearingDataReceived, tags=['DTU'])
async def receive_bearing_data(bearing_id: str, data: BearingData):
    try:
        payload = data.model_dump()
        payload.pop('bearing_id', None)
        return dtu.receive(bearing_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get('/api/bearing/{bearing_id}/latest', tags=['DTU'])
async def get_latest_data(bearing_id: str):
    cached = dtu.get_latest(bearing_id)
    if cached:
        return cached
    rows = db.query_bearing_data(bearing_id, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail=f'轴承 {bearing_id} 无数据')
    point = rows[0]
    return point


@app.post('/api/bearing/{bearing_id}/history', tags=['DTU'])
async def get_history(bearing_id: str, query: HistoryQuery):
    try:
        rows = db.query_bearing_data(
            bearing_id,
            start_time=query.start_time,
            end_time=query.end_time,
            limit=query.limit,
            fields=query.fields,
        )
    except Exception as e:
        log.exception('历史查询失败: %s', e)
        raise HTTPException(status_code=500, detail=str(e))
    return {'bearing_id': bearing_id, 'count': len(rows), 'data': rows}


@app.get('/api/bearing/{bearing_id}/stats', tags=['DTU'])
async def get_stats(bearing_id: str, hours: int = 24):
    rows = db.query_bearing_data(bearing_id, limit=10000)
    if not rows:
        raise HTTPException(status_code=404, detail=f'轴承 {bearing_id} 无数据')
    fields = ['rpm', 'water_pressure', 'friction_coefficient',
              'water_temperature', 'power_loss_watts']
    stats = {'bearing_id': bearing_id, 'hours': hours, 'count': len(rows)}
    for f in fields:
        vals = [r.get(f) for r in rows if isinstance(r.get(f), (int, float))]
        if not vals:
            continue
        stats[f] = {
            'min': min(vals), 'max': max(vals),
            'avg': sum(vals) / len(vals), 'last': vals[-1],
        }
    return stats


# ---------- 仿真计算 (Flow + Friction) ----------
@app.post('/api/simulation/calculate', response_model=SimulationResponse, tags=['Simulation'])
async def calculate_simulation(req: SimulationRequest):
    # 1. 直接调用流场仿真（非消息驱动，以降低延迟）
    flow = flow_sim.compute(
        rpm=req.rpm,
        eccentricity_ratio=req.eccentricity_ratio,
        temperature=req.temperature,
        viscosity_model=req.viscosity_model,
    )
    flow['bearing_id'] = req.bearing_id

    # 2. 摩擦功耗分析
    friction = friction_svc.compute_from_flow(
        flow,
        load_n=req.load_n if req.load_n else None,
        viscosity_model=req.viscosity_model,
    )
    friction['bearing_id'] = req.bearing_id

    # 3. 告警评估
    alerts = alarm_svc.evaluate(req.bearing_id or 'adhoc', flow, friction)
    alarm_svc.push_alerts(alerts)

    # 4. 发布到总线（供其他订阅者消费）
    bus.publish('flow_result', flow)
    bus.publish('friction_result', friction)

    return SimulationResponse(
        bearing_id=req.bearing_id,
        rpm=req.rpm,
        load_capacity=flow['load_capacity_n'],
        attitude_angle_rad=flow['attitude_angle_rad'],
        pressure_distribution=flow['pressure_distribution_pa'],
        film_thickness=flow['film_thickness_m'],
        max_pressure_pa=flow['max_pressure_pa'],
        min_film_thickness_m=flow['min_film_thickness_m'],
        friction_coefficient=friction['friction_coefficient'],
        friction_torque_nm=friction['friction_torque_nm'],
        power_loss_watts=friction['power_loss_watts'],
        flow_rate_m3s=friction['flow_rate_m3s'],
        cavitation_area_fraction=flow['cavitation_area_fraction'],
        vapor_fraction_max=flow['max_vapor_fraction'],
        temperature_inlet_k=friction['inlet_temperature_k'],
        temperature_outlet_k=friction['outlet_temperature_k'],
        film_rupture_risk=flow['film_rupture_risk'],
        film_status=flow['film_status'],
        power_status=friction['power_status'],
        alerts_generated=len(alerts),
        solver_converged=flow['solver_converged'],
        solver_iterations=flow['solver_iterations'],
    )


@app.get('/api/simulation/{bearing_id}/last', tags=['Simulation'])
async def get_last_simulation(bearing_id: str):
    flow = flow_sim.get_last_result(bearing_id)
    friction = friction_svc.get_last_result(bearing_id)
    if not flow and not friction:
        raise HTTPException(status_code=404, detail=f'轴承 {bearing_id} 无仿真记录')
    return {'flow': flow, 'friction': friction}


# ---------- 告警 ----------
@app.get('/api/alerts', response_model=List[Alert], tags=['Alert'])
async def list_alerts(bearing_id: Optional[str] = None, limit: int = 50):
    raw = alarm_svc.get_history(limit=limit, bearing_id=bearing_id)
    out = []
    for r in raw:
        try:
            out.append(Alert(**r))
        except Exception:
            out.append(Alert(
                bearing_id=r.get('bearing_id', ''),
                type=r.get('type', 'unknown'),
                severity=r.get('severity', 'info'),
                message=r.get('message', ''),
                value=r.get('value'),
                timestamp=r.get('timestamp') or datetime.now(timezone.utc),
            ))
    return out


# ---------- WebSocket ----------
@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    client_id = str(uuid.uuid4())
    await alarm_svc.manager.connect(websocket, client_id)
    try:
        await websocket.send_json({
            'type': 'welcome', 'client_id': client_id,
            'server_time': datetime.now(timezone.utc).isoformat(),
        })
        for bid in dtu.list_recent_ids():
            cached = dtu.get_latest(bid)
            if cached:
                await websocket.send_json({'type': 'bearing_data', 'data': cached})
        for a in alarm_svc.get_history(limit=10):
            await websocket.send_json({'type': 'alert', 'data': a})

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
                if data.get('type') == 'ping':
                    await websocket.send_json({'type': 'pong', 'ts': datetime.now(timezone.utc).isoformat()})
            except asyncio.TimeoutError:
                await websocket.send_json({'type': 'ping', 'ts': datetime.now(timezone.utc).isoformat()})
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        alarm_svc.manager.disconnect(client_id)


@app.on_event('shutdown')
async def _on_shutdown():
    bus.close()
    db.close()
