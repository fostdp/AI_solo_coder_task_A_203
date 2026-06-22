"""
宋代筒车水润滑轴承模拟器 - v3.0
职责：基于配置参数生成物理仿真的传感器数据，通过消息总线或REST推送到系统。
"""
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

# 允许直接 python backend/simulator.py 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import (
    get_bearing_config,
    get_fluid_config,
    get_nested,
)
from backend.messaging import MessageBus
from backend.services import (
    AlarmWebSocketService,
    DTUReceiver,
    FlowSimulator,
    FrictionAnalyzerService,
)
from backend.simulation import CavitationModel, FrictionAnalyzer, WaterFilmSolver
from backend.simulation.friction import ViscosityTemperatureModel

log = logging.getLogger(__name__)


class BearingSimulator:
    """
    生成物理合理的轴承传感器数据。
    数据链路: 内部物理仿真 → 可选通过DTUReceiver验证+存储+总线发布
    """

    def __init__(self, bearing_id: str,
                 use_bus: bool = True,
                 rest_endpoint: Optional[str] = None):
        self.bearing_id = bearing_id
        self.cfg_bearing = get_bearing_config()
        self.cfg_fluid = get_fluid_config()

        default = get_nested(self.cfg_bearing, 'bearing.song_dynasty_water_wheel', {})
        self.R = float(default.get('radius_m', 0.05))
        self.L = float(default.get('length_m', 0.2))
        self.c = float(default.get('clearance_m', 0.0001))
        self.grid_size = int(get_nested(self.cfg_bearing, 'solver.reynolds_equation.grid_size', 32))
        self.base_rpm = float(get_nested(self.cfg_bearing, 'friction.rated_rpm', 50.0) * 0.6)
        self.base_load = float(get_nested(self.cfg_bearing, 'friction.rated_load_n', 1500.0) * 0.5)
        self.base_supply_temp = float(self.cfg_fluid.get('reference_temperature', 293.15))

        self.mu0 = float(self.cfg_fluid.get('reference_viscosity', 1.002e-3))
        self.viscosity_model_name = self.cfg_fluid.get('viscosity_model', 'andrade')
        self.viscosity_model = ViscosityTemperatureModel(model_type=self.viscosity_model_name)

        self.water_solver = WaterFilmSolver(
            grid_size=self.grid_size,
            bearing_radius=self.R,
            bearing_length=self.L,
            radial_clearance=self.c,
        )
        self.cavitation = CavitationModel(
            vapor_pressure=float(self.cfg_fluid.get('vapor_pressure', 2338.8)),
            surface_tension=float(self.cfg_fluid.get('surface_tension', 0.0728)),
            density=float(self.cfg_fluid.get('density', 1000.0)),
        )
        self.friction = FrictionAnalyzer(
            bearing_radius=self.R,
            bearing_length=self.L,
            radial_clearance=self.c,
            viscosity=self.mu0,
            viscosity_model=self.viscosity_model_name,
            reference_temp=self.base_supply_temp,
        )

        self.use_bus = use_bus
        self.rest_endpoint = rest_endpoint
        self.simulated_hours: int = 0
        self.total_wear: float = 0.0

        if use_bus:
            self.bus = MessageBus.instance()
            self.dtu = DTUReceiver(bus=self.bus)
        else:
            self.bus = None
            self.dtu = None

    def _update_temperature_dependent_properties(self, temperature_k: float) -> float:
        return self.viscosity_model.calculate_viscosity(temperature_k)

    def generate_reading(self) -> Dict[str, Any]:
        """生成一小时的仿真读数。"""
        self.simulated_hours += 1
        t = self.simulated_hours
        time_frac = t / 24.0

        rpm = (self.base_rpm + 8.0 * np.sin(2 * np.pi * time_frac)
               + np.random.normal(0, 2.0))
        rpm = float(np.clip(rpm, 3.0, 120.0))
        omega = rpm * 2.0 * np.pi / 60.0

        water_temp_k = (self.base_supply_temp + 5.0 * np.sin(2 * np.pi * time_frac - np.pi / 4)
                        + np.random.normal(0, 0.3))
        mu_eff = self._update_temperature_dependent_properties(water_temp_k)

        wear_per_hour = 1e-7 * (rpm / self.base_rpm) ** 2
        self.total_wear += wear_per_hour + float(np.random.normal(0, 5e-8))
        self.total_wear = max(0.0, self.total_wear)

        eccentricity_ratio = (0.25 + 10.0 * self.total_wear
                              + 0.06 * np.sin(2 * np.pi * time_frac - np.pi / 6)
                              + np.random.normal(0, 0.012))
        eccentricity_ratio = float(np.clip(eccentricity_ratio, 0.02, 0.85))

        self.water_solver.mu = mu_eff
        self.water_solver.calculate_film_thickness(eccentricity_ratio * self.c)
        pressure_result = self.water_solver.solve_pressure(omega)
        p = pressure_result['pressure']
        h = pressure_result['film_thickness']

        cav_result = self.cavitation.detect_cavitation(p, h, omega)
        rupture_result = self.cavitation.assess_film_rupture(p, h, omega)
        velocity = self.water_solver.calculate_velocity_field(omega)

        load = self.base_load + np.random.normal(0, self.base_load * 0.06)
        full_analysis = self.friction.full_analysis(
            omega=omega, load=float(load),
            eccentricity_ratio=eccentricity_ratio,
            pressure_field=p, film_thickness=h,
            temperature=water_temp_k, viscosity_model=self.viscosity_model_name,
            iterate_temperature=True,
        )

        max_p = float(np.max(p))
        min_h = float(np.min(h))
        avg_u = float(np.mean(np.abs(velocity['u'])))
        warning = self.friction.assess_power_warning(
            full_analysis['power_loss_watts'],
            full_analysis.get('temperature_rise', 0.0),
        )

        return {
            'rpm': float(rpm),
            'water_pressure': float(max_p / 1000.0),
            'friction_coefficient': float(full_analysis['friction_coefficient']),
            'water_temperature': float(water_temp_k - 273.15),
            'power_loss_watts': float(full_analysis['power_loss_watts']),
            'flow_rate_m3s': float(full_analysis['flow_rate']),
            'eccentricity_ratio': float(eccentricity_ratio),
            'load_capacity_n': float(pressure_result['load_capacity']),
            'max_pressure_pa': float(max_p),
            'min_film_thickness_micron': float(min_h * 1e6),
            'avg_velocity_mps': float(avg_u),
            'cavitation_area_fraction': float(cav_result['cavitation_area_fraction']),
            'vapor_fraction_max': float(cav_result['max_vapor_fraction']),
            'film_status': rupture_result['status'],
            'power_status': warning['status'],
            'bearing_id': self.bearing_id,
            'timestamp': datetime.now(timezone.utc),
            'simulated_hour': self.simulated_hours,
        }

    def publish(self, reading: Dict[str, Any]) -> None:
        if self.use_bus and self.dtu is not None:
            try:
                self.dtu.receive(self.bearing_id, reading)
                log.info('[%s] t=%dh 推送完成: rpm=%.1f, fc=%.4f, T=%.1f°C',
                         self.bearing_id, self.simulated_hours,
                         reading['rpm'], reading['friction_coefficient'],
                         reading['water_temperature'])
            except Exception as e:
                log.exception('总线推送失败: %s', e)
        if self.rest_endpoint:
            payload = {k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                       for k, v in reading.items()}
            try:
                req = urllib.request.Request(
                    f'{self.rest_endpoint}/api/bearing/{self.bearing_id}/data',
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    log.debug('REST HTTP %s', resp.status)
            except urllib.error.URLError as e:
                log.warning('REST推送失败: %s', e)

    def run(self, max_hours: Optional[int] = None, interval_seconds: float = 1.0) -> None:
        log.info('模拟器启动 bearing=%s, bus=%s, rest=%s',
                 self.bearing_id, self.use_bus, self.rest_endpoint)
        try:
            while True:
                reading = self.generate_reading()
                self.publish(reading)
                if max_hours and self.simulated_hours >= max_hours:
                    log.info('达到最大模拟小时数 %d, 退出', max_hours)
                    break
                time.sleep(max(0.05, interval_seconds))
        except KeyboardInterrupt:
            log.info('用户中断，已模拟 %d 小时', self.simulated_hours)


def run_all_known(interval_seconds: float = 1.0, max_hours: Optional[int] = None):
    cfg = get_nested(get_bearing_config(), 'known_bearings', [])
    sims: List[BearingSimulator] = [
        BearingSimulator(b['id']) for b in cfg
    ]
    log.info('启动 %d 个轴承模拟器', len(sims))
    hrs = 0
    try:
        while True:
            for s in sims:
                reading = s.generate_reading()
                s.publish(reading)
            hrs += 1
            if max_hours and hrs >= max_hours:
                break
            time.sleep(max(0.05, interval_seconds))
    except KeyboardInterrupt:
        log.info('用户中断')


if __name__ == '__main__':
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'),
                        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    interval = float(os.getenv('SIM_INTERVAL', '1.0'))
    max_h = int(os.getenv('SIM_MAX_HOURS', '0')) or None
    rest = os.getenv('SIM_REST_ENDPOINT')
    bid = os.getenv('SIM_BEARING_ID')
    if bid:
        sim = BearingSimulator(bid, use_bus=not rest, rest_endpoint=rest)
        sim.run(interval_seconds=interval, max_hours=max_h)
    else:
        run_all_known(interval_seconds=interval, max_hours=max_h)
