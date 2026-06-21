from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class BearingData(BaseModel):
    rpm: float = Field(..., description="转速 (RPM)")
    water_pressure: float = Field(..., description="平均水膜压力 (Pa)")
    max_pressure: Optional[float] = Field(None, description="最大水膜压力 (Pa)")
    friction_coefficient: float = Field(..., description="摩擦系数")
    water_temperature: float = Field(..., description="水温 (°C)")
    eccentricity_ratio: Optional[float] = Field(None, description="偏心率")
    min_film_thickness: Optional[float] = Field(None, description="最小水膜厚度 (m)")
    load_capacity: Optional[float] = Field(None, description="承载能力 (N)")
    friction_torque: Optional[float] = Field(None, description="摩擦力矩 (N·m)")
    power_loss: Optional[float] = Field(None, description="摩擦功耗 (W)")
    sommerfeld_number: Optional[float] = Field(None, description="Sommerfeld数")
    temperature_rise: Optional[float] = Field(None, description="温升 (K)")
    flow_rate: Optional[float] = Field(None, description="流量 (m³/s)")
    cavitation_area_fraction: Optional[float] = Field(None, description="空化面积比")
    cavitation_max_vapor_fraction: Optional[float] = Field(None, description="最大蒸汽体积分数")
    has_cavitation: Optional[bool] = Field(None, description="是否发生空化")
    rupture_risk: Optional[float] = Field(None, description="水膜破裂风险")
    film_status: Optional[str] = Field(None, description="水膜状态: normal/warning/ruptured")
    power_status: Optional[str] = Field(None, description="功耗状态: normal/warning/overload")
    attitude_angle: Optional[float] = Field(None, description="偏位角 (rad)")
    timestamp: Optional[str] = Field(None, description="时间戳")


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


class SimulationRequest(BaseModel):
    rpm: float = Field(35.0, description="转速 (RPM)")
    eccentricity_ratio: float = Field(0.3, description="偏心率")
    water_temperature: float = Field(22.0, description="水温 (°C)")
    bearing_radius: float = Field(0.05, description="轴承半径 (m)")
    bearing_length: float = Field(0.08, description="轴承长度 (m)")
    radial_clearance: float = Field(2e-4, description="径向间隙 (m)")
    load: float = Field(800.0, description="载荷 (N)")


class SimulationResponse(BaseModel):
    pressure_distribution: List[float]
    film_thickness: List[float]
    theta: List[float]
    max_pressure: float
    min_pressure: float
    load_capacity: float
    attitude_angle: float
    friction_coefficient: float
    power_loss: float
    friction_torque: float
    cavitation_area_fraction: float
    has_cavitation: bool
    rupture_risk: float
    film_status: str
    temperature_rise: float
    velocity_profiles: Optional[Dict[str, List[float]]] = None


class BearingListResponse(BaseModel):
    bearings: List[str]


class HistoryQuery(BaseModel):
    bearing_id: str
    start_time: str = "-1h"
    end_time: str = "now()"
    fields: Optional[List[str]] = None


class StatsResponse(BaseModel):
    bearing_id: str
    avg_rpm: float
    avg_pressure: float
    avg_friction_coeff: float
    avg_temp: float
    max_power_loss: float
    avg_power_loss: float
    avg_eccentricity: float
    alert_count: int
    data_points: int
