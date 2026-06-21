import numpy as np
from typing import Dict, Optional


def _trapz(y, x=None, dx=1.0, axis=-1):
    if hasattr(np, 'trapezoid'):
        if x is not None:
            return np.trapezoid(y, x, axis=axis)
        return np.trapezoid(y, dx=dx, axis=axis)
    if x is not None:
        return np.trapz(y, x, axis=axis)
    return np.trapz(y, dx=dx, axis=axis)


class FrictionAnalyzer:
    def __init__(
        self,
        bearing_radius: float = 0.05,
        bearing_length: float = 0.08,
        radial_clearance: float = 2e-4,
        viscosity: float = 1.002e-3,
        density: float = 1000.0,
        specific_heat: float = 4186.0,
    ):
        self.R = bearing_radius
        self.L = bearing_length
        self.c = radial_clearance
        self.mu = viscosity
        self.rho = density
        self.c_p = specific_heat

    def calculate_friction_coefficient(
        self,
        omega: float,
        eccentricity_ratio: float,
        sommerfeld_number: Optional[float] = None,
    ) -> Dict:
        if sommerfeld_number is None:
            sommerfeld_number = (self.mu * omega * self.R / (self.c ** 2)) * (
                (self.R / self.c) * (self.L / (2 * self.R)) ** 2
            )

        epsilon = eccentricity_ratio

        if epsilon < 0.8:
            f_Rc = 2 * np.pi ** 2 * (self.R / self.c) / (
                np.sqrt(sommerfeld_number * (1 + 1.5 * epsilon ** 2))
            )
        else:
            f_Rc = (np.pi ** 2 * (self.R / self.c)) / (
                sommerfeld_number * (1 - epsilon ** 2) ** 1.5
            ) * (1 + 0.5 * epsilon ** 2)

        friction_coeff = f_Rc * (self.c / self.R)

        return {
            'friction_coefficient': friction_coeff,
            'sommerfeld_number': sommerfeld_number,
            'f_Rc': f_Rc,
        }

    def calculate_friction_torque(
        self,
        omega: float,
        load: float,
        eccentricity_ratio: float,
        pressure_field: Optional[np.ndarray] = None,
        film_thickness: Optional[np.ndarray] = None,
    ) -> Dict:
        friction_result = self.calculate_friction_coefficient(omega, eccentricity_ratio)
        f = friction_result['friction_coefficient']

        torque_coulomb = f * load * self.R

        if pressure_field is not None and film_thickness is not None:
            torque_shear = self._calculate_shear_torque(
                pressure_field, film_thickness, omega
            )
        else:
            torque_shear = torque_coulomb * 0.8

        total_torque = torque_shear + torque_coulomb * 0.2

        return {
            'friction_torque': total_torque,
            'shear_torque': torque_shear,
            'coulomb_torque': torque_coulomb,
            'friction_coefficient': f,
        }

    def _calculate_shear_torque(
        self,
        pressure: np.ndarray,
        film_thickness: np.ndarray,
        omega: float,
    ) -> float:
        h = film_thickness
        mu = self.mu
        R = self.R
        n_theta, n_z = pressure.shape
        dtheta = 2 * np.pi / n_theta
        dz = self.L / n_z

        u_surface = omega * R

        shear_stress = mu * u_surface / h + 0.5 * h * np.gradient(pressure, dtheta, axis=0) / R

        torque = _trapz(
            _trapz(shear_stress * R, dx=dz, axis=1),
            dx=dtheta
        ) * R

        return abs(torque)

    def calculate_power_loss(
        self,
        omega: float,
        load: float,
        eccentricity_ratio: float,
        pressure_field: Optional[np.ndarray] = None,
        film_thickness: Optional[np.ndarray] = None,
    ) -> Dict:
        torque_result = self.calculate_friction_torque(
            omega, load, eccentricity_ratio, pressure_field, film_thickness
        )

        power_loss = torque_result['friction_torque'] * omega

        return {
            'power_loss': power_loss,
            'friction_torque': torque_result['friction_torque'],
            'shear_torque': torque_result['shear_torque'],
            'coulomb_torque': torque_result['coulomb_torque'],
            'friction_coefficient': torque_result['friction_coefficient'],
        }

    def calculate_heat_generation(
        self,
        power_loss: float,
        flow_rate: float,
        inlet_temp: float = 293.15,
    ) -> Dict:
        temp_rise = power_loss / (self.rho * self.c_p * flow_rate) if flow_rate > 0 else float('inf')
        outlet_temp = inlet_temp + temp_rise

        return {
            'temperature_rise': temp_rise,
            'outlet_temperature': outlet_temp,
            'inlet_temperature': inlet_temp,
            'heat_flux': power_loss / (2 * np.pi * self.R * self.L),
        }

    def calculate_flow_rate(
        self,
        omega: float,
        eccentricity_ratio: float,
        supply_pressure: float = 101325.0,
        ambient_pressure: float = 101325.0,
    ) -> Dict:
        epsilon = eccentricity_ratio
        h_avg = self.c * (1 + epsilon ** 2 / 2)

        q_couette = np.pi * self.R * omega * self.c * (1 - epsilon)

        delta_p = supply_pressure - ambient_pressure
        q_poiseuille = (np.pi * self.R * h_avg ** 3 * delta_p) / (6 * self.mu * self.L)

        total_flow = q_couette + q_poiseuille

        return {
            'flow_rate': total_flow,
            'couette_flow': q_couette,
            'poiseuille_flow': q_poiseuille,
        }

    def assess_power_warning(
        self,
        power_loss: float,
        max_power: float = 500.0,
        warning_threshold: float = 0.7,
    ) -> Dict:
        power_ratio = power_loss / max_power

        is_overload = power_ratio > 1.0
        is_warning = power_ratio > warning_threshold

        return {
            'power_loss': power_loss,
            'max_power': max_power,
            'power_ratio': power_ratio,
            'is_overload': is_overload,
            'is_warning': is_warning,
            'status': 'overload' if is_overload else ('warning' if is_warning else 'normal'),
        }

    def full_analysis(
        self,
        omega: float,
        load: float,
        eccentricity_ratio: float,
        pressure_field: Optional[np.ndarray] = None,
        film_thickness: Optional[np.ndarray] = None,
        inlet_temp: float = 293.15,
        supply_pressure: float = 101325.0,
        max_power: float = 500.0,
    ) -> Dict:
        power_result = self.calculate_power_loss(
            omega, load, eccentricity_ratio, pressure_field, film_thickness
        )

        flow_result = self.calculate_flow_rate(omega, eccentricity_ratio, supply_pressure)

        heat_result = self.calculate_heat_generation(
            power_result['power_loss'], flow_result['flow_rate'], inlet_temp
        )

        warning_result = self.assess_power_warning(power_result['power_loss'], max_power)

        return {
            **power_result,
            **flow_result,
            **heat_result,
            **warning_result,
            'eccentricity_ratio': eccentricity_ratio,
            'rotational_speed_rpm': omega * 60 / (2 * np.pi),
        }

    def update_viscosity(self, temperature: float):
        mu_0 = 1.792e-3
        T0 = 273.15
        self.mu = mu_0 * np.exp(-1.8 * (temperature - T0) / T0)
        return self.mu
