import numpy as np
from typing import Dict, Optional, Tuple


class RayleighPlessetSolver:
    def __init__(
        self,
        surface_tension: float = 0.0728,
        viscosity: float = 1.002e-3,
        density: float = 1000.0,
        vapor_pressure: float = 2338.8,
        polytropic_index: float = 1.4,
    ):
        self.sigma = surface_tension
        self.mu = viscosity
        self.rho = density
        self.p_vap = vapor_pressure
        self.gamma = polytropic_index

    def solve_equilibrium_radius(self, ambient_pressure: float,
                                  initial_radius: float = 1e-5) -> float:
        R_eq = initial_radius
        for _ in range(50):
            p_in = self.p_vap + 2 * self.sigma / R_eq
            p_out = ambient_pressure + 2 * self.sigma / R_eq
            dp = p_in - p_out
            if abs(dp) < 1e-3:
                break
            R_eq = R_eq * (1 + 0.1 * np.sign(dp))
            R_eq = max(1e-7, min(R_eq, 1e-2))
        return R_eq

    def rayleigh_plesset_rhs(self, R: float, dR_dt: float,
                             ambient_pressure: float) -> Tuple[float, float]:
        if R < 1e-8:
            return dR_dt, 0.0

        p_gas = self.p_vap * (1e-5 / R) ** (3 * self.gamma)

        p_in = p_gas + 2 * self.sigma / R
        p_out = ambient_pressure + 2 * self.sigma / R + 4 * self.mu * dR_dt / R

        dp = p_in - p_out

        if abs(R) < 1e-10:
            d2R_dt2 = 0.0
        else:
            d2R_dt2 = (dp / self.rho - 1.5 * dR_dt ** 2 - 4 * self.mu * dR_dt / (self.rho * R)
                       - 2 * self.sigma / (self.rho * R)) / R

        return dR_dt, d2R_dt2

    def integrate(self, R0: float, dR_dt0: float, ambient_pressure: float,
                  dt: float, n_steps: int = 50) -> Tuple[float, float]:
        R = R0
        dR_dt = dR_dt0

        R_max = 1e-2
        dR_dt_max = 100.0
        d2R_dt2_max = 1e8

        for _ in range(n_steps):
            dt_sub = dt / n_steps

            try:
                _, k1_v = self.rayleigh_plesset_rhs(R, dR_dt, ambient_pressure)
                k1_v = np.clip(k1_v, -d2R_dt2_max, d2R_dt2_max)

                R2 = R + 0.5 * dt_sub * dR_dt
                dR2 = dR_dt + 0.5 * dt_sub * k1_v
                R2 = np.clip(R2, 1e-8, R_max)
                dR2 = np.clip(dR2, -dR_dt_max, dR_dt_max)
                _, k2_v = self.rayleigh_plesset_rhs(R2, dR2, ambient_pressure)
                k2_v = np.clip(k2_v, -d2R_dt2_max, d2R_dt2_max)

                R3 = R + 0.5 * dt_sub * (dR_dt + 0.5 * dt_sub * k1_v)
                dR3 = dR_dt + 0.5 * dt_sub * k2_v
                R3 = np.clip(R3, 1e-8, R_max)
                dR3 = np.clip(dR3, -dR_dt_max, dR_dt_max)
                _, k3_v = self.rayleigh_plesset_rhs(R3, dR3, ambient_pressure)
                k3_v = np.clip(k3_v, -d2R_dt2_max, d2R_dt2_max)

                R4 = R + dt_sub * (dR_dt + 0.5 * dt_sub * k2_v)
                dR4 = dR_dt + dt_sub * k3_v
                R4 = np.clip(R4, 1e-8, R_max)
                dR4 = np.clip(dR4, -dR_dt_max, dR_dt_max)
                _, k4_v = self.rayleigh_plesset_rhs(R4, dR4, ambient_pressure)
                k4_v = np.clip(k4_v, -d2R_dt2_max, d2R_dt2_max)

                new_R = R + dt_sub * dR_dt + dt_sub ** 2 / 6 * (k1_v + k2_v + k3_v)
                new_dR_dt = dR_dt + dt_sub / 6 * (k1_v + 2 * k2_v + 2 * k3_v + k4_v)

                new_R = np.clip(new_R, 1e-8, R_max)
                new_dR_dt = np.clip(new_dR_dt, -dR_dt_max, dR_dt_max)

                if np.isnan(new_R) or np.isnan(new_dR_dt) or np.isinf(new_R) or np.isinf(new_dR_dt):
                    break

                R = float(new_R)
                dR_dt = float(new_dR_dt)

            except (OverflowError, FloatingPointError):
                break

        return R, dR_dt

    def calculate_bubble_growth_rate(self, R: float, ambient_pressure: float) -> float:
        if R < 1e-8:
            return 0.0

        p_in = self.p_vap + 2 * self.sigma / R
        p_out = ambient_pressure

        if p_in > p_out:
            dR_dt = np.sqrt(2 * (p_in - p_out) / (3 * self.rho))
        else:
            dR_dt = -np.sqrt(2 * (p_out - p_in) / (3 * self.rho))

        dR_dt = dR_dt / (1 + 4 * self.mu / (self.rho * R * abs(dR_dt) + 1e-10))
        return dR_dt

    def calculate_cavitation_threshold(self, frequency: float = 100.0) -> float:
        if frequency < 1e-3:
            R_blake = 2 * self.sigma / (self.p_amb - self.p_vap + 1e-10)
            p_threshold = self.p_vap + 0.77 * (2 * self.sigma / R_blake)
        else:
            omega = 2 * np.pi * frequency
            R_res = np.sqrt(3 * self.gamma * self.p_vap / (self.rho * omega ** 2))
            p_threshold = self.p_vap - 0.5 * self.rho * omega ** 2 * R_res ** 2

        return max(p_threshold, 100.0)

    def calculate_bubble_collapse_energy(self, R_max: float, R_min: float = 1e-8) -> float:
        if R_max <= R_min:
            return 0.0
        energy = 4 * np.pi * self.p_vap / 3 * (R_max ** 3 - R_min ** 3)
        energy += 4 * np.pi * self.sigma * (R_max ** 2 - R_min ** 2)
        return max(0, energy)


class CavitationModel:
    def __init__(
        self,
        vapor_pressure: float = 2338.8,
        ambient_pressure: float = 101325.0,
        surface_tension: float = 0.0728,
        viscosity: float = 1.002e-3,
        density: float = 1000.0,
        gas_constant: float = 287.0,
        temperature: float = 293.15,
        alpha_coef: float = 50.0,
        beta_coef: float = 0.001,
        nucleation_site_density: float = 1e12,
    ):
        self.p_vap = vapor_pressure
        self.p_amb = ambient_pressure
        self.sigma = surface_tension
        self.mu = viscosity
        self.rho = density
        self.R_g = gas_constant
        self.T = temperature
        self.alpha = alpha_coef
        self.beta = beta_coef
        self.nucleation_density = nucleation_site_density

        self.rp_solver = RayleighPlessetSolver(
            surface_tension=surface_tension,
            viscosity=viscosity,
            density=density,
            vapor_pressure=vapor_pressure,
        )

        self.cavitation_region = None
        self.vapor_fraction = None
        self.bubble_radius = None
        self.bubble_growth_rate = None
        self.collapse_energy = None

    def _get_dynamic_cavitation_threshold(self, omega: float = 0.0) -> float:
        if omega < 0.1:
            return self.p_vap

        frequency = omega / (2 * np.pi)
        R_crit = np.sqrt(2 * self.sigma / (self.rho * omega ** 2))

        p_threshold = self.p_vap + 2 * self.sigma / R_crit * (1 - 1 / np.sqrt(3))
        p_threshold -= 0.5 * self.rho * omega ** 2 * R_crit ** 2

        return max(p_threshold, self.p_vap * 0.5)

    def detect_cavitation(self, pressure_field: np.ndarray,
                          film_thickness: np.ndarray,
                          omega: float = 0.0) -> Dict:
        p = pressure_field
        h = film_thickness

        p_cav = self._get_dynamic_cavitation_threshold(omega)

        self.cavitation_region = p < p_cav
        self.vapor_fraction = np.zeros_like(p)
        self.bubble_radius = np.zeros_like(p)
        self.bubble_growth_rate = np.zeros_like(p)

        cav_mask = self.cavitation_region & (h > 1e-6)

        if np.any(cav_mask):
            p_cav_points = p[cav_mask]
            h_cav_points = h[cav_mask]

            R0 = np.ones_like(p_cav_points) * 1e-6
            dR_dt0 = np.zeros_like(p_cav_points)

            R_eq = np.zeros_like(p_cav_points)
            growth_rate = np.zeros_like(p_cav_points)

            for i in range(len(p_cav_points)):
                R, dR_dt = self.rp_solver.integrate(
                    R0[i], dR_dt0[i], p_cav_points[i], dt=1e-4, n_steps=20
                )
                R_eq[i] = min(R, h_cav_points[i] * 0.45)
                growth_rate[i] = dR_dt

            self.bubble_radius[cav_mask] = R_eq
            self.bubble_growth_rate[cav_mask] = growth_rate

            n_bubbles = self.nucleation_density * h_cav_points * (2 * R_eq) ** 2
            vapor_volume = n_bubbles * (4 * np.pi / 3) * R_eq ** 3
            total_volume = h_cav_points * 1.0
            self.vapor_fraction[cav_mask] = np.minimum(vapor_volume / total_volume, 0.95)

        non_cav_mask = ~self.cavitation_region
        self.vapor_fraction[non_cav_mask] = 1.0 / (
            1.0 + self.beta * (p[non_cav_mask] - self.p_vap) / self.p_amb
        )
        self.vapor_fraction[non_cav_mask] = np.minimum(
            self.vapor_fraction[non_cav_mask], 0.01
        )

        cavitation_area_fraction = np.sum(self.cavitation_region) / self.cavitation_region.size
        max_vapor_fraction = np.max(self.vapor_fraction)

        superheated = p < self.p_vap * 0.8
        superheated_fraction = np.sum(superheated) / superheated.size

        return {
            'cavitation_region': self.cavitation_region,
            'vapor_fraction': self.vapor_fraction,
            'bubble_radius': self.bubble_radius,
            'bubble_growth_rate': self.bubble_growth_rate,
            'cavitation_area_fraction': cavitation_area_fraction,
            'max_vapor_fraction': max_vapor_fraction,
            'cavitation_threshold': p_cav,
            'superheated_fraction': superheated_fraction,
            'has_cavitation': cavitation_area_fraction > 0.01,
            'is_dynamic_cavitation': omega > 1.0 and cavitation_area_fraction > 0.01,
        }

    def calculate_collapse_energy_field(self, pressure_field: np.ndarray) -> np.ndarray:
        if self.bubble_radius is None:
            return np.zeros_like(pressure_field)

        self.collapse_energy = np.zeros_like(pressure_field)
        collapsing = self.bubble_growth_rate < 0

        if np.any(collapsing):
            R_max = self.bubble_radius[collapsing]
            self.collapse_energy[collapsing] = self.rp_solver.calculate_bubble_collapse_energy(
                R_max, R_min=1e-8
            )

        return self.collapse_energy

    def calculate_surface_tension(self, temperature: Optional[float] = None) -> float:
        if temperature is not None:
            self.T = temperature
            self.sigma = 0.2358 * (1.0 - temperature / 647.096) ** 1.256
            self.rp_solver.sigma = self.sigma
        return self.sigma

    def calculate_vapor_pressure(self, temperature: Optional[float] = None) -> float:
        if temperature is not None:
            self.T = temperature
            T_c = 647.096
            T_r = temperature / T_c
            P_c = 22.064e6
            a1 = -7.85951783
            a2 = 1.84408259
            a3 = -11.7866497
            a4 = 22.6807411
            a5 = -15.9618719
            a6 = 1.80122502
            tau = 1 - T_r
            self.p_vap = P_c * np.exp(
                (a1 * tau + a2 * tau ** 1.5 + a3 * tau ** 3 +
                 a4 * tau ** 3.5 + a5 * tau ** 4 + a6 * tau ** 7.5) / T_r
            )
            self.rp_solver.p_vap = self.p_vap
        return self.p_vap

    def update_viscosity(self, viscosity: float):
        self.mu = viscosity
        self.rp_solver.mu = viscosity

    def apply_cavitation_correction(self, pressure: np.ndarray,
                                    film_thickness: np.ndarray,
                                    omega: float = 0.0,
                                    max_iter: int = 50) -> np.ndarray:
        p_corrected = pressure.copy()
        h = film_thickness

        for _ in range(max_iter):
            cav_result = self.detect_cavitation(p_corrected, h, omega)

            if not cav_result['has_cavitation']:
                break

            alpha_v = cav_result['vapor_fraction']
            mu_mix = self.mu_mixture(alpha_v)

            dyn_threshold = cav_result['cavitation_threshold']
            cav_region = cav_result['cavitation_region']

            p_corrected[cav_region] = dyn_threshold * (
                1.0 + 0.1 * alpha_v[cav_region]
            )

        return p_corrected

    def mu_mixture(self, vapor_fraction: np.ndarray,
                   mu_liquid: Optional[float] = None,
                   mu_vapor: float = 9.8e-6) -> np.ndarray:
        if mu_liquid is None:
            mu_liquid = self.mu

        alpha = np.clip(vapor_fraction, 0, 0.99)
        mu_relative = mu_vapor / mu_liquid

        mu_mix = mu_liquid * (1 - alpha) ** 2.5 * (
            1 + alpha * (mu_relative - 1) / (mu_relative + 2 / 3)
        )

        crit = 0.5
        transition = 0.5 + 0.5 * np.tanh((alpha - crit) * 10)
        mu_foam = mu_liquid * (1 - alpha) / (1 + 3 * alpha)
        mu_mix = mu_mix * (1 - transition) + mu_foam * transition

        return mu_mix

    def assess_film_rupture(self, pressure: np.ndarray,
                            film_thickness: np.ndarray,
                            omega: float = 0.0,
                            min_film_ratio: float = 0.1,
                            cavitation_threshold: float = 0.3) -> Dict:
        h_min = np.min(film_thickness)
        h_min_ratio = h_min / np.mean(film_thickness)

        cav_result = self.detect_cavitation(pressure, film_thickness, omega)
        cav_fraction = cav_result['cavitation_area_fraction']

        low_pressure_ratio = np.sum(pressure < self.p_amb * 0.1) / pressure.size

        if self.bubble_growth_rate is not None:
            high_growth = np.sum(np.abs(self.bubble_growth_rate) > 1.0) / pressure.size
        else:
            high_growth = 0.0

        rupture_risk = 0.0
        rupture_risk += min(h_min_ratio * 5, 1.0) * 0.3
        rupture_risk += min(cav_fraction / cavitation_threshold, 1.0) * 0.35
        rupture_risk += min(low_pressure_ratio / 0.2, 1.0) * 0.15
        rupture_risk += min(high_growth / 0.1, 1.0) * 0.2

        is_ruptured = rupture_risk > 0.7
        is_warning = rupture_risk > 0.4

        return {
            'min_film_thickness': h_min,
            'min_film_ratio': h_min_ratio,
            'cavitation_area_fraction': cav_fraction,
            'low_pressure_ratio': low_pressure_ratio,
            'high_growth_fraction': high_growth,
            'rupture_risk': rupture_risk,
            'is_ruptured': is_ruptured,
            'is_warning': is_warning,
            'status': 'ruptured' if is_ruptured else ('warning' if is_warning else 'normal'),
        }

    def update_temperature(self, temperature: float):
        self.calculate_surface_tension(temperature)
        self.calculate_vapor_pressure(temperature)
