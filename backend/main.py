"""
古代筒车轴承水润滑流场仿真与摩擦功耗分析系统 - FastAPI 后端
"""
import os
import sys
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))

from database.influxdb_client import InfluxDBClientWrapper
from simulation import WaterFilmSolver, CavitationModel, FrictionAnalyzer
from models.bearing import (
    BearingData,
    BearingDataResponse,
    AlertMessage,
    SimulationRequest,
    SimulationResponse,
    BearingListResponse,
    StatsResponse,
)

app = FastAPI(
    title="古代筒车轴承水润滑流场仿真与摩擦功耗分析系统",
    description="基于Navier-Stokes方程和空化模型的水润滑轴承仿真分析平台",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_client = InfluxDBClientWrapper()

active_connections: Set[WebSocket] = set()

alert_history: List[Dict] = []

bearing_cache: Dict[str, Dict] = {}

KNOWN_BEARINGS = ["bearing_001", "bearing_002", "bearing_003"]


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()


def check_alerts(bearing_id: str, data: dict) -> List[dict]:
    alerts = []
    now = datetime.utcnow()

    film_status = data.get('film_status', 'normal')
    rupture_risk = data.get('rupture_risk', 0.0)

    if film_status == 'ruptured':
        alerts.append({
            'alert_type': 'film_rupture',
            'bearing_id': bearing_id,
            'severity': 'critical',
            'message': f'水膜破裂警报！轴承 {bearing_id} 水膜已破裂，破裂风险: {rupture_risk:.2f}',
            'data': {
                'rupture_risk': rupture_risk,
                'min_film_thickness': data.get('min_film_thickness'),
                'eccentricity_ratio': data.get('eccentricity_ratio'),
                'cavitation_area_fraction': data.get('cavitation_area_fraction'),
            },
            'timestamp': now.isoformat() + "Z",
        })
    elif film_status == 'warning':
        alerts.append({
            'alert_type': 'film_warning',
            'bearing_id': bearing_id,
            'severity': 'warning',
            'message': f'水膜警告！轴承 {bearing_id} 水膜状态异常，破裂风险: {rupture_risk:.2f}',
            'data': {
                'rupture_risk': rupture_risk,
                'min_film_thickness': data.get('min_film_thickness'),
                'eccentricity_ratio': data.get('eccentricity_ratio'),
            },
            'timestamp': now.isoformat() + "Z",
        })

    power_status = data.get('power_status', 'normal')
    power_loss = data.get('power_loss', 0.0)

    if power_status == 'overload':
        alerts.append({
            'alert_type': 'power_overload',
            'bearing_id': bearing_id,
            'severity': 'critical',
            'message': f'功耗过载警报！轴承 {bearing_id} 摩擦功耗过高: {power_loss:.2f} W',
            'data': {
                'power_loss': power_loss,
                'friction_coefficient': data.get('friction_coefficient'),
                'rpm': data.get('rpm'),
            },
            'timestamp': now.isoformat() + "Z",
        })
    elif power_status == 'warning':
        alerts.append({
            'alert_type': 'power_warning',
            'bearing_id': bearing_id,
            'severity': 'warning',
            'message': f'功耗警告！轴承 {bearing_id} 摩擦功耗偏高: {power_loss:.2f} W',
            'data': {
                'power_loss': power_loss,
                'friction_coefficient': data.get('friction_coefficient'),
                'rpm': data.get('rpm'),
            },
            'timestamp': now.isoformat() + "Z",
        })

    if data.get('has_cavitation', False):
        cav_fraction = data.get('cavitation_area_fraction', 0)
        if cav_fraction > 0.2:
            alerts.append({
                'alert_type': 'cavitation_severe',
                'bearing_id': bearing_id,
                'severity': 'warning',
                'message': f'严重空化！轴承 {bearing_id} 空化面积比: {cav_fraction * 100:.1f}%',
                'data': {
                    'cavitation_area_fraction': cav_fraction,
                    'max_vapor_fraction': data.get('cavitation_max_vapor_fraction'),
                },
                'timestamp': now.isoformat() + "Z",
            })

    return alerts


@app.get("/")
async def root():
    return {
        "name": "古代筒车轴承水润滑流场仿真与摩擦功耗分析系统",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "sensor_data": "/api/bearing/{bearing_id}/data",
            "latest_data": "/api/bearing/{bearing_id}/latest",
            "history": "/api/bearing/{bearing_id}/history",
            "simulation": "/api/simulation/calculate",
            "alerts": "/api/alerts",
            "websocket": "/ws",
        }
    }


@app.get("/api/bearings", response_model=BearingListResponse)
async def list_bearings():
    bearings = list(set(KNOWN_BEARINGS + list(bearing_cache.keys())))
    return {"bearings": bearings}


@app.post("/api/bearing/{bearing_id}/data", response_model=BearingDataResponse)
async def receive_bearing_data(bearing_id: str, data: BearingData):
    data_dict = data.dict()
    timestamp = datetime.utcnow()

    bearing_cache[bearing_id] = {
        **data_dict,
        "received_at": timestamp.isoformat() + "Z",
    }

    fields = {k: v for k, v in data_dict.items()
              if isinstance(v, (int, float)) and v is not None}

    try:
        db_client.write_bearing_data(bearing_id, fields, timestamp)
    except Exception as e:
        print(f"Warning: Failed to write to InfluxDB: {e}")

    alerts = check_alerts(bearing_id, data_dict)
    for alert in alerts:
        alert_history.append(alert)
        if len(alert_history) > 100:
            alert_history.pop(0)
        asyncio.create_task(manager.broadcast({
            "type": "alert",
            "data": alert,
        }))

    asyncio.create_task(manager.broadcast({
        "type": "bearing_data",
        "data": {
            "bearing_id": bearing_id,
            **data_dict,
            "received_at": timestamp.isoformat() + "Z",
        },
    }))

    return {
        "bearing_id": bearing_id,
        "data": data,
        "received_at": timestamp,
    }


@app.get("/api/bearing/{bearing_id}/latest")
async def get_latest_data(bearing_id: str):
    if bearing_id in bearing_cache:
        return {
            "bearing_id": bearing_id,
            "data": bearing_cache[bearing_id],
            "source": "cache",
        }

    db_data = db_client.get_latest_data(bearing_id)
    if db_data:
        return {
            "bearing_id": bearing_id,
            "data": db_data,
            "source": "influxdb",
        }

    raise HTTPException(status_code=404, detail=f"No data found for bearing {bearing_id}")


@app.get("/api/bearing/{bearing_id}/history")
async def get_history_data(
    bearing_id: str,
    start_time: str = "-1h",
    end_time: str = "now()",
):
    records = db_client.query_bearing_data(
        bearing_id=bearing_id,
        start_time=start_time,
        end_time=end_time,
    )

    time_series = {}
    for record in records:
        t = record["time"].isoformat() if hasattr(record["time"], "isoformat") else str(record["time"])
        field = record["field"]
        value = record["value"]

        if t not in time_series:
            time_series[t] = {}
        time_series[t][field] = value

    result = [
        {"time": t, **values}
        for t, values in sorted(time_series.items())
    ]

    return {
        "bearing_id": bearing_id,
        "start_time": start_time,
        "end_time": end_time,
        "data_points": len(result),
        "data": result,
    }


@app.get("/api/bearing/{bearing_id}/stats", response_model=StatsResponse)
async def get_bearing_stats(bearing_id: str, start_time: str = "-24h"):
    records = db_client.query_bearing_data(
        bearing_id=bearing_id,
        start_time=start_time,
    )

    if not records:
        raise HTTPException(status_code=404, detail=f"No data found for bearing {bearing_id}")

    field_values = {}
    for record in records:
        field = record["field"]
        value = record["value"]
        if field not in field_values:
            field_values[field] = []
        field_values[field].append(value)

    rpm_values = field_values.get("rpm", [0])
    pressure_values = field_values.get("water_pressure", [0])
    friction_values = field_values.get("friction_coefficient", [0])
    temp_values = field_values.get("water_temperature", [0])
    power_values = field_values.get("power_loss", [0])
    eccentricity_values = field_values.get("eccentricity_ratio", [0])

    alert_count = sum(1 for a in alert_history if a["bearing_id"] == bearing_id)

    return StatsResponse(
        bearing_id=bearing_id,
        avg_rpm=sum(rpm_values) / len(rpm_values) if rpm_values else 0,
        avg_pressure=sum(pressure_values) / len(pressure_values) if pressure_values else 0,
        avg_friction_coeff=sum(friction_values) / len(friction_values) if friction_values else 0,
        avg_temp=sum(temp_values) / len(temp_values) if temp_values else 0,
        max_power_loss=max(power_values) if power_values else 0,
        avg_power_loss=sum(power_values) / len(power_values) if power_values else 0,
        avg_eccentricity=sum(eccentricity_values) / len(eccentricity_values) if eccentricity_values else 0,
        alert_count=alert_count,
        data_points=len(records),
    )


@app.post("/api/simulation/calculate", response_model=SimulationResponse)
async def run_simulation(req: SimulationRequest):
    temp_k = req.water_temperature + 273.15
    mu_0 = 1.792e-3
    T0 = 273.15
    viscosity = mu_0 * (2.71828 ** (-1.8 * (temp_k - T0) / T0))

    solver = WaterFilmSolver(
        bearing_radius=req.bearing_radius,
        bearing_length=req.bearing_length,
        radial_clearance=req.radial_clearance,
        eccentricity=req.eccentricity_ratio * req.radial_clearance,
        viscosity=viscosity,
    )

    cavitation = CavitationModel(temperature=temp_k)
    friction = FrictionAnalyzer(
        bearing_radius=req.bearing_radius,
        bearing_length=req.bearing_length,
        radial_clearance=req.radial_clearance,
        viscosity=viscosity,
    )

    omega = req.rpm * 2 * 3.141592653589793 / 60

    solver.calculate_film_thickness(req.eccentricity_ratio * req.radial_clearance)
    pressure_result = solver.solve_pressure(omega)
    pressure = pressure_result['pressure']
    film_thickness = pressure_result['film_thickness']

    cav_result = cavitation.detect_cavitation(pressure, film_thickness, omega)
    rupture_result = cavitation.assess_film_rupture(pressure, film_thickness, omega)

    actual_load = min(req.load, pressure_result['load_capacity'] * 0.8)
    friction_result = friction.full_analysis(
        omega=omega,
        load=actual_load,
        eccentricity_ratio=req.eccentricity_ratio,
        pressure_field=pressure,
        film_thickness=film_thickness,
        inlet_temp=temp_k,
    )

    mid_z_idx = solver.n_z // 2
    pressure_1d = pressure[:, mid_z_idx].tolist()
    film_1d = film_thickness[:, mid_z_idx].tolist()
    theta_list = solver.theta.tolist()

    return SimulationResponse(
        pressure_distribution=pressure_1d,
        film_thickness=film_1d,
        theta=theta_list,
        max_pressure=pressure_result['max_pressure'],
        min_pressure=pressure_result['min_pressure'],
        load_capacity=pressure_result['load_capacity'],
        attitude_angle=pressure_result['attitude_angle'],
        friction_coefficient=friction_result['friction_coefficient'],
        power_loss=friction_result['power_loss'],
        friction_torque=friction_result['friction_torque'],
        cavitation_area_fraction=cav_result['cavitation_area_fraction'],
        has_cavitation=cav_result['has_cavitation'],
        rupture_risk=rupture_result['rupture_risk'],
        film_status=rupture_result['status'],
        temperature_rise=friction_result['temperature_rise'],
    )


@app.get("/api/simulation/velocity")
async def get_velocity_field(
    rpm: float = 35.0,
    eccentricity_ratio: float = 0.3,
    water_temperature: float = 22.0,
):
    temp_k = water_temperature + 273.15
    mu_0 = 1.792e-3
    T0 = 273.15
    viscosity = mu_0 * (2.71828 ** (-1.8 * (temp_k - T0) / T0))

    solver = WaterFilmSolver(viscosity=viscosity, grid_size=32)
    solver.calculate_film_thickness(eccentricity_ratio * solver.c)
    omega = rpm * 2 * 3.141592653589793 / 60
    solver.solve_pressure(omega)
    velocity = solver.calculate_velocity_field(omega)

    mid_z_idx = solver.n_z // 2
    u_mid = velocity['u'][:, mid_z_idx, :]
    v_mid = velocity['v'][:, mid_z_idx, :]

    return {
        "theta": solver.theta.tolist(),
        "y_normalized": velocity['y_normalized'].tolist(),
        "u_velocity": u_mid.tolist(),
        "v_velocity": v_mid.tolist(),
        "rpm": rpm,
        "eccentricity_ratio": eccentricity_ratio,
    }


@app.get("/api/alerts")
async def get_alerts(limit: int = 50, bearing_id: Optional[str] = None):
    alerts = alert_history[-limit:]
    if bearing_id:
        alerts = [a for a in alerts if a["bearing_id"] == bearing_id]
    return {
        "count": len(alerts),
        "alerts": list(reversed(alerts)),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket 连接已建立",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

        for bearing_id in bearing_cache:
            await websocket.send_json({
                "type": "bearing_data",
                "data": {
                    "bearing_id": bearing_id,
                    **bearing_cache[bearing_id],
                },
            })

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat() + "Z"})
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@app.get("/api/health")
async def health_check():
    influx_status = db_client.test_connection()
    return {
        "status": "healthy",
        "influxdb_connected": influx_status,
        "websocket_connections": len(manager.active_connections),
        "cached_bearings": len(bearing_cache),
        "alert_count": len(alert_history),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/app")
    async def serve_frontend():
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
