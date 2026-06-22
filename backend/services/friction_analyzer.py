"""摩擦功耗分析器：订阅flow_result，结合参数计算摩擦/温升/流量，发布friction_result。"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np

from ..config import get_bearing_config, get_fluid_config, get_messaging_config, get_nested
from ..messaging import MessageBus
from ..simulation import FrictionAnalyzer
from ..simulation.friction import ViscosityTemperatureModel

log = logging.getLogger(__name__)


class FrictionAnalyzerService:
    """
    订阅: bearing:flow_result
    发布: bearing:friction_result
    """

    def __init__(self, bus: Optional[MessageBus] = None, auto_subscribe: bool = True):
        self.bus = bus or MessageBus.instance()
        self.fluid_cfg = get_fluid_config()
        self.bearing_cfg = get_bearing_config()
        self.msg_cfg = get_messaging_config()

        bearing_default = get_nested(self.bearing_cfg, 'bearing.song_dynasty_water_wheel', {})
        R = float(bearing_default.get('radius_m', 0.05))
        L = float(bearing_default.get('length_m', 0.2))
        c = float(bearing_default.get('clearance_m', 0.0001))
        friction_cfg = get_nested(self.bearing_cfg, 'friction', {})
        mu0 = float(self.fluid_cfg.get('reference_viscosity', 1.002e-3))

        self._analyzer = FrictionAnalyzer(
            bearing_radius=R,
            bearing_length=L,
            radial_clearance=c,
            viscosity=mu0,
            viscosity_model=self.fluid_cfg.get('viscosity_model', 'andrade'),
            reference_temp=float(self.fluid_cfg.get('reference_temperature_k', 293.15)),
        )
        self.viscosity_model = self.fluid_cfg.get('viscosity_model', 'andrade')
        self.rated_load = float(friction_cfg.get('rated_load_n', 1500.0))
        self.rated_power = float(friction_cfg.get('rated_power_w', 50.0))
        self._last_results: Dict[str, Dict[str, Any]] = {}

        if auto_subscribe:
            self.bus.subscribe('flow_result', self._on_flow_result)
            self.bus.subscribe('simulation_request', self._on_sim_request)
            log.info('FrictionAnalyzerService 已订阅 flow_result / simulation_request')

    # ---------- 核心计算 ----------
    def compute_from_flow(self, flow: Dict[str, Any],
                          load_n: Optional[float] = None,
                          viscosity_model: Optional[str] = None) -> Dict[str, Any]:
        rpm = float(flow.get('rpm', 30.0))
        omega = float(flow.get('omega_rad_s', rpm * 2.0 * np.pi / 60.0))
        ecc = float(flow.get('eccentricity_ratio', 0.3))
        T = flow.get('temperature')
        if T is not None:
            T = float(T)
        model = viscosity_model or self.viscosity_model

        p = np.array(flow['pressure_distribution_pa'], dtype=float)
        h = np.array(flow['film_thickness_m'], dtype=float)
        load = load_n or float(flow.get('load_capacity_n', self.rated_load))

        full_result = self._analyzer.full_analysis(
            omega=omega,
            load=load,
            eccentricity_ratio=ecc,
            pressure_field=p,
            film_thickness=h,
            inlet_temp=T if T is not None else 293.15,
            viscosity_model=model,
            iterate_temperature=True,
        )
        warning = full_result.get('warning', {}) or {}
        warning_status = warning.get('status', 'normal')
        warning_severity = warning.get('severity', 'normal')
        power_loss_w = float(full_result['power_loss'])
        return {
            'bearing_id': flow.get('bearing_id'),
            'timestamp': datetime.utcnow().isoformat(),
            'rpm': rpm,
            'omega_rad_s': omega,
            'load_capacity_n': float(load),
            'eccentricity_ratio': ecc,
            'inlet_temperature_k': float(full_result.get('inlet_temperature', T if T is not None else 293.15)),
            'outlet_temperature_k': float(full_result.get('outlet_temperature', T if T is not None else 293.15)),
            'temperature_rise_k': float(full_result.get('temperature_rise', 0.0)),
            'viscosity_model': full_result.get('viscosity_model', model),
            'effective_viscosity_pa_s': float(full_result.get('effective_viscosity')),
            'friction_coefficient': float(full_result['friction_coefficient']),
            'sommerfeld_number': float(full_result.get('sommerfeld_number', 0.0)),
            'friction_torque_nm': float(full_result['friction_torque']),
            'power_loss_watts': power_loss_w,
            'heat_generation_watts': power_loss_w,
            'heat_flux_wm2': float(full_result.get('heat_flux', 0.0)),
            'flow_rate_m3s': float(full_result.get('flow_rate', 0.0)),
            'reynolds_number': float(full_result.get('reynolds_number', 0.0)),
            'prandtl_number': float(full_result.get('prandtl_number', 0.0)),
            'nusselt_number': float(full_result.get('nusselt_number', 0.0)),
            'heat_transfer_coefficient': float(full_result.get('heat_transfer_coeff', 0.0)),
            'power_ratio_to_rated': power_loss_w / self.rated_power,
            'power_status': warning_status,
            'power_severity': warning_severity,
            'coupled_iterations': int(full_result.get('iterations', 1)),
            'coupled_converged': bool(full_result.get('converged', True)),
        }

    # ---------- 消息驱动 ----------
    def _on_flow_result(self, flow: Dict[str, Any]) -> None:
        bearing_id = flow.get('bearing_id')
        if not bearing_id:
            return
        try:
            result = self.compute_from_flow(flow)
        except Exception as e:
            log.exception('摩擦分析失败 bearing=%s: %s', bearing_id, e)
            return
        result['bearing_id'] = bearing_id
        result['source'] = 'flow_result'
        self._last_results[bearing_id] = result
        self.bus.publish('friction_result', result)
        try:
            ttl = get_nested(self.msg_cfg, 'cache_ttl_seconds.friction_result', 1800)
            self.bus.setex(f'bearing:friction:{bearing_id}', int(ttl), result)
        except Exception:
            pass

    def _on_sim_request(self, payload: Dict[str, Any]) -> None:
        """与FlowSimulator协同：已在simulation_response中处理，此处仅做摩擦侧补充。"""
        pass  # 统一由编排层组合

    def get_last_result(self, bearing_id: str) -> Optional[Dict[str, Any]]:
        cached = self._last_results.get(bearing_id)
        if cached:
            return cached
        return self.bus.get(f'bearing:friction:{bearing_id}')


__all__ = ['FrictionAnalyzerService']
