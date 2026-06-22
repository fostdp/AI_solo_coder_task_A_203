"""v3.0 数据模型 — 覆盖DTU接收、仿真请求/响应、告警、轴承元数据、历史查询。"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============== DTU 数据接收 ==============
class BearingData(BaseModel):
    bearing_id: Optional[str] = Field(None, description="轴承ID（路由参数优先）")
    rpm: float = Field(..., description="转速 (RPM)")
    water_pressure: float = Field(..., description="平均水膜压力 (kPa)")
    friction_coefficient: float = Field(..., description="摩擦系数")
    water_temperature: float = Field(..., description="水温 (°C)")
    power_loss_watts: Optional[float] = Field(None, description="摩擦功耗 (W)")
    flow_rate_m3s: Optional[float] = Field(None, description="流量 (m³/s)")
    eccentricity_ratio: Optional[float] = Field(None, description="偏心率")
    load_capacity_n: Optional[float] = Field(None, description="承载能力 (N)")
    max_pressure_pa: Optional[float] = Field(None, description="最大水膜压力 (Pa)")
    min_film_thickness_micron: Optional[float] = Field(None, description="最小水膜厚度 (μm)")
    avg_velocity_mps: Optional[float] = Field(None, description="平均流速 (m/s)")
    cavitation_area_fraction: Optional[float] = Field(None, description="空化面积比 (0-1)")
    vapor_fraction_max: Optional[float] = Field(None, description="最大蒸汽体积分数")
    film_status: Optional[str] = Field(None, description="水膜状态 normal/warning/ruptured")
    power_status: Optional[str] = Field(None, description="功耗状态 normal/warning/overload")
    location: Optional[str] = Field(None, description="位置/站点")
    timestamp: Optional[datetime] = Field(None, description="时间戳")


class BearingDataReceived(BaseModel):
    bearing_id: str
    timestamp: datetime
    status: str = "accepted"
    message: str = ""


# ============== 轴承元数据 ==============
class BearingInfo(BaseModel):
    id: str
    name: str = ""
    location: str = ""
    description: str = ""


# ============== 仿真计算 ==============
class SimulationRequest(BaseModel):
    bearing_id: Optional[str] = Field(None, description="轴承ID")
    rpm: float = Field(35.0, description="转速 (RPM)")
    eccentricity_ratio: float = Field(0.3, description="偏心率")
    load_n: Optional[float] = Field(None, description="载荷 (N)；None则用雷诺方程求解的承载力")
    temperature: Optional[float] = Field(None, description="温度 (K)；None则用参考温度")
    viscosity_model: Optional[str] = Field("andrade", description="andrade/reynolds/walther/vogel/polynomial")


class SimulationResponse(BaseModel):
    bearing_id: Optional[str] = None
    rpm: float
    load_capacity: float
    attitude_angle_rad: float
    pressure_distribution: List[float]
    film_thickness: List[float]
    max_pressure_pa: float
    min_film_thickness_m: float
    friction_coefficient: float
    friction_torque_nm: float
    power_loss_watts: float
    flow_rate_m3s: float
    cavitation_area_fraction: float
    vapor_fraction_max: float
    temperature_inlet_k: float
    temperature_outlet_k: float
    film_rupture_risk: float
    film_status: str
    power_status: str
    alerts_generated: int = 0
    solver_converged: bool = False
    solver_iterations: int = 0


# ============== 历史查询 ==============
class HistoryQuery(BaseModel):
    bearing_id: Optional[str] = None
    start_time: str = "-24h"
    end_time: str = "now()"
    limit: int = 1000
    fields: Optional[List[str]] = None


# ============== 告警 ==============
class Alert(BaseModel):
    bearing_id: str
    type: str
    severity: str
    message: str
    value: Optional[Any] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============== 废弃兼容（保留） ==============
class BearingDataResponse(BaseModel):
    bearing_id: str
    data: BearingData
    received_at: datetime


class AlertMessage(BaseModel):
    alert_type: str
    bearing_id: str
    severity: str
    message: str
    data: Dict[str, Any]
    timestamp: datetime


class BearingListResponse(BaseModel):
    bearings: List[str]


class StatsResponse(BaseModel):
    bearing_id: str
    avg_rpm: Optional[float] = None
    avg_pressure: Optional[float] = None
    avg_friction_coeff: Optional[float] = None
    avg_temp: Optional[float] = None
    max_power_loss: Optional[float] = None
    avg_power_loss: Optional[float] = None
    avg_eccentricity: Optional[float] = None
    alert_count: int = 0
    data_points: int = 0
