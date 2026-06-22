"""流场仿真器：订阅DTU发布的raw_data，运行雷诺方程+空化模型，发布flow_result。"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np

from ..config import get_bearing_config, get_fluid_config, get_messaging_config, get_nested
from ..messaging import MessageBus
from ..simulation import CavitationModel, WaterFilmSolver

log = logging.getLogger(__name__)


class FlowSimulator:
    """
    订阅: bearing:raw_data
    发布: bearing:flow_result
    """

    def __init__(self, bus: Optional[MessageBus] = None, auto_subscribe: bool = True):
        self.bus = bus or MessageBus.instance()
        self.fluid_cfg = get_fluid_config()
        self.bearing_cfg = get_bearing_config()
        self.msg_cfg = get_messaging_config()

        solver_cfg = get_nested(self.bearing_cfg, 'solver.reynolds_equation', {})
        self.grid_size = int(solver_cfg.get('grid_size', 32))
        self.bearing_default = get_nested(
            self.bearing_cfg, 'bearing.song_dynasty_water_wheel', {})
        self.R = float(self.bearing_default.get('radius_m', 0.05))
        self.L = float(self.bearing_default.get('length_m', 0.2))
        self.c = float(self.bearing_default.get('clearance_m', 0.0001))
        self.viscosity_model = self.fluid_cfg.get('viscosity_model', 'andrade')

        self._solver = WaterFilmSolver(
            grid_size=self.grid_size,
            bearing_radius=self.R,
            bearing_length=self.L,
            radial_clearance=self.c,
        )
        self._cavitation = CavitationModel(
            vapor_pressure=float(self.fluid_cfg.get('vapor_pressure', 2338.8)),
            surface_tension=float(self.fluid_cfg.get('surface_tension', 0.0728)),
            density=float(self.fluid_cfg.get('density', 1000.0)),
        )
        self._last_results: Dict[str, Dict[str, Any]] = {}

        if auto_subscribe:
            self.bus.subscribe('raw_data', self._on_raw_data)
            self.bus.subscribe('simulation_request', self._on_sim_request)
            log.info('FlowSimulator 已订阅 raw_data / simulation_request')

    # ---------- 核心计算 ----------
    def compute(self, rpm: float, eccentricity_ratio: float,
                temperature: Optional[float] = None,
                viscosity_model: Optional[str] = None) -> Dict[str, Any]:
        """
        执行雷诺方程求解 + 空化检测 + 水膜破裂评估。
        """
        omega = rpm * 2.0 * np.pi / 60.0
        model = viscosity_model or self.viscosity_model

        if temperature is not None:
            from ..simulation.friction import ViscosityTemperatureModel
            vt = ViscosityTemperatureModel(model_type=model)
            mu = vt.calculate_viscosity(temperature)
        else:
            mu = float(self.fluid_cfg.get('reference_viscosity', 1.002e-3))

        self._solver.mu = mu
        self._solver.calculate_film_thickness(eccentricity_ratio * self.c)
        pres_result = self._solver.solve_pressure(omega)

        cav_result = self._cavitation.detect_cavitation(
            pres_result['pressure'], pres_result['film_thickness'], omega,
        )
        rupture = self._cavitation.assess_film_rupture(
            pres_result['pressure'], pres_result['film_thickness'], omega,
        )
        velocity = self._solver.calculate_velocity_field(omega)

        return {
            'bearing_id': None,
            'timestamp': datetime.utcnow().isoformat(),
            'rpm': rpm,
            'omega_rad_s': float(omega),
            'eccentricity_ratio': eccentricity_ratio,
            'temperature': temperature,
            'viscosity_model': model,
            'effective_viscosity': float(mu),
            'pressure_distribution_pa': pres_result['pressure'].tolist(),
            'film_thickness_m': pres_result['film_thickness'].tolist(),
            'velocity_u_mps': velocity['u'].tolist(),
            'load_capacity_n': float(pres_result['load_capacity']),
            'attitude_angle_rad': float(pres_result.get('attitude_angle', 0.0)),
            'max_pressure_pa': float(np.max(pres_result['pressure'])),
            'min_film_thickness_m': float(np.min(pres_result['film_thickness'])),
            'cavitation_area_fraction': float(cav_result['cavitation_area_fraction']),
            'max_vapor_fraction': float(cav_result['max_vapor_fraction']),
            'cavitation_threshold_pa': float(cav_result['cavitation_threshold']),
            'bubble_growth_rate_max_mps': float(np.max(cav_result.get('bubble_growth_rate', [0.0]))),
            'is_dynamic_cavitation': bool(cav_result.get('is_dynamic_cavitation', False)),
            'film_rupture_risk': float(rupture['rupture_risk']),
            'film_status': rupture['status'],
            'solver_converged': bool(pres_result.get('converged', False)),
            'solver_iterations': int(pres_result.get('iterations', 0)),
        }

    # ---------- 消息驱动 ----------
    def _on_raw_data(self, payload: Dict[str, Any]) -> None:
        bearing_id = payload.get('bearing_id')
        if not bearing_id:
            return
        rpm = float(payload.get('rpm', 30.0))
        ecc = float(payload.get('eccentricity_ratio', 0.3))
        T = payload.get('water_temperature')
        T = float(T) if T is not None else None

        try:
            result = self.compute(rpm, ecc, temperature=T)
        except Exception as e:
            log.exception('FlowSimulator 计算失败 bearing=%s: %s', bearing_id, e)
            return
        result['bearing_id'] = bearing_id
        result['source'] = 'raw_data'
        self._last_results[bearing_id] = result
        self.bus.publish('flow_result', result)
        try:
            ttl = get_nested(self.msg_cfg, 'cache_ttl_seconds.flow_result', 1800)
            self.bus.setex(f'bearing:flow:{bearing_id}', int(ttl), result)
        except Exception:
            pass

    def _on_sim_request(self, payload: Dict[str, Any]) -> None:
        rpm = float(payload.get('rpm', 30.0))
        ecc = float(payload.get('eccentricity_ratio', 0.3))
        T = payload.get('temperature')
        T = float(T) if T is not None else None
        model = payload.get('viscosity_model') or self.viscosity_model
        try:
            result = self.compute(rpm, ecc, temperature=T, viscosity_model=model)
        except Exception as e:
            log.exception('FlowSimulator 仿真计算失败: %s', e)
            result = {'error': str(e)}
        result['bearing_id'] = payload.get('bearing_id')
        result['source'] = 'simulation_request'
        if payload.get('__reply_to__'):
            self.bus.reply(payload, result)
        self.bus.publish('simulation_response', result)

    def get_last_result(self, bearing_id: str) -> Optional[Dict[str, Any]]:
        cached = self._last_results.get(bearing_id)
        if cached:
            return cached
        return self.bus.get(f'bearing:flow:{bearing_id}')


__all__ = ['FlowSimulator']
