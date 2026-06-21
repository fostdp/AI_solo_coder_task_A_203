import numpy as np
from typing import Dict, Optional, Tuple


class CavitationModel:
    def __init__(
        self,
        vapor_pressure: float = 2338.8,
        ambient_pressure: float = 101325.0,
        surface_tension: float = 0.0728,
        gas_constant: float = 287.0,
        temperature: float = 293.15,
        alpha_coef: float = 50.0,
        beta_coef: float = 0.001,
    ):
        self.p_vap = vapor_pressure
        self.p_amb = ambient_pressure
        self.sigma = surface_tension
        self.R_g = gas_constant
        self.T = temperature
        self.alpha = alpha_coef
        self.beta = beta_coef

        self.cavitation_region = None
        self.vapor_fraction = None
        self.bubble_radius = None

    def detect_cavitation(self, pressure_field: np.ndarray,
                          film_thickness: np.ndarray) -> Dict:
        p = pressure_field
        h = film_thickness

        self.cavitation_region = p < self.p_vap
        self.vapor_fraction = np.zeros_like(p)

        pressure_ratio = np.maximum(p, 1e-3) / self.p_vap
        self.vapor_fraction = np.where(
            self.cavitation_region,
            1.0 / (1.0 + self.beta * (self.p_vap - p) / self.p_amb),
            0.0
        )

        self.bubble_radius = np.zeros_like(p)
        cav_mask = self.cavitation_region & (h > 1e-6)
        self.bubble_radius[cav_mask] = np.minimum(
            2 * self.sigma / np.maximum(self.p_vap - p[cav_mask], 1e-6),
            h[cav_mask] * 0.5
        )

        cavitation_area_fraction = np.sum(self.cavitation_region) / self.cavitation_region.size
        max_vapor_fraction = np.max(self.vapor_fraction)

        return {
            'cavitation_region': self.cavitation_region,
            'vapor_fraction': self.vapor_fraction,
            'bubble_radius': self.bubble_radius,
            'cavitation_area_fraction': cavitation_area_fraction,
            'max_vapor_fraction': max_vapor_fraction,
            'has_cavitation': cavitation_area_fraction > 0.01,
        }

    def calculate_surface_tension(self, temperature: Optional[float] = None) -> float:
        if temperature is not None:
            self.T = temperature
            self.sigma = 0.2358 * (1.0 - temperature / 647.096) ** 1.256
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
        return self.p_vap

    def apply_cavitation_correction(self, pressure: np.ndarray,
                                    film_thickness: np.ndarray,
                                    max_iter: int = 50) -> np.ndarray:
        p_corrected = pressure.copy()
        h = film_thickness

        for _ in range(max_iter):
            cav_result = self.detect_cavitation(p_corrected, h)

            if not cav_result['has_cavitation']:
                break

            alpha_v = cav_result['vapor_fraction']
            mu_mix = self.mu_mixture(alpha_v)

            p_corrected[self.cavitation_region] = self.p_vap * (
                1.0 + 0.1 * alpha_v[self.cavitation_region]
            )

        return p_corrected

    def mu_mixture(self, vapor_fraction: np.ndarray,
                   mu_liquid: float = 1.002e-3,
                   mu_vapor: float = 9.8e-6) -> np.ndarray:
        alpha = vapor_fraction
        mu_relative = mu_vapor / mu_liquid
        mu_mix = mu_liquid * (1 - alpha) ** 2.5 * (
            1 + alpha * (mu_relative - 1) / (mu_relative + 2 / 3)
        )
        return mu_mix

    def assess_film_rupture(self, pressure: np.ndarray,
                            film_thickness: np.ndarray,
                            min_film_ratio: float = 0.1,
                            cavitation_threshold: float = 0.3) -> Dict:
        h_min = np.min(film_thickness)
        h_min_ratio = h_min / np.mean(film_thickness)

        cav_result = self.detect_cavitation(pressure, film_thickness)
        cav_fraction = cav_result['cavitation_area_fraction']

        low_pressure_ratio = np.sum(pressure < self.p_amb * 0.1) / pressure.size

        rupture_risk = 0.0
        rupture_risk += min(h_min_ratio * 5, 1.0) * 0.4
        rupture_risk += min(cav_fraction / cavitation_threshold, 1.0) * 0.4
        rupture_risk += min(low_pressure_ratio / 0.2, 1.0) * 0.2

        is_ruptured = rupture_risk > 0.7
        is_warning = rupture_risk > 0.4

        return {
            'min_film_thickness': h_min,
            'min_film_ratio': h_min_ratio,
            'cavitation_area_fraction': cav_fraction,
            'low_pressure_ratio': low_pressure_ratio,
            'rupture_risk': rupture_risk,
            'is_ruptured': is_ruptured,
            'is_warning': is_warning,
            'status': 'ruptured' if is_ruptured else ('warning' if is_warning else 'normal'),
        }

    def update_temperature(self, temperature: float):
        self.calculate_surface_tension(temperature)
        self.calculate_vapor_pressure(temperature)
