import numpy as np
from typing import Dict, Tuple, Optional


def _trapz(y, x, axis=-1):
    if hasattr(np, 'trapezoid'):
        return np.trapezoid(y, x, axis=axis)
    return np.trapz(y, x, axis=axis)


class WaterFilmSolver:
    def __init__(
        self,
        bearing_radius: float = 0.05,
        bearing_length: float = 0.08,
        radial_clearance: float = 2e-4,
        eccentricity: float = 0.0,
        viscosity: float = 1.002e-3,
        density: float = 1000.0,
        ambient_pressure: float = 101325.0,
        grid_size: int = 64,
    ):
        self.R = bearing_radius
        self.L = bearing_length
        self.c = radial_clearance
        self.e = eccentricity
        self.mu = viscosity
        self.rho = density
        self.p_amb = ambient_pressure
        self.n_theta = grid_size
        self.n_z = grid_size

        self.theta = np.linspace(0, 2 * np.pi, self.n_theta, endpoint=False)
        self.z = np.linspace(-self.L / 2, self.L / 2, self.n_z)
        self.Theta, self.Z = np.meshgrid(self.theta, self.z, indexing='ij')

        self.pressure = np.ones((self.n_theta, self.n_z)) * self.p_amb
        self.film_thickness = None
        self.velocity = None
        self.cavitation = None

    def calculate_film_thickness(self, eccentricity: Optional[float] = None) -> np.ndarray:
        if eccentricity is not None:
            self.e = eccentricity
        self.film_thickness = self.c * (1 + (self.e / self.c) * np.cos(self.Theta))
        return self.film_thickness

    def _reynolds_residual(self, p: np.ndarray, omega: float) -> np.ndarray:
        h = self.film_thickness
        h3 = h ** 3
        dtheta = self.theta[1] - self.theta[0]
        dz = self.z[1] - self.z[0]

        dp_dtheta = np.gradient(p, dtheta, axis=0)
        dp_dz = np.gradient(p, dz, axis=1)

        d2p_dtheta2 = np.gradient(dp_dtheta, dtheta, axis=0)
        d2p_dz2 = np.gradient(dp_dz, dz, axis=1)

        dh_dtheta = np.gradient(h, dtheta, axis=0)

        lhs = (1 / self.R ** 2) * d2p_dtheta2 + d2p_dz2
        rhs = 6 * self.mu * omega * dh_dtheta / self.R

        residual = h3 * lhs + 3 * h ** 2 * (dh_dtheta / self.R * dp_dtheta + 0 * dp_dz) - rhs
        return residual

    def solve_pressure(self, omega: float, max_iter: int = 500, tol: float = 1e-6,
                       relaxation: float = 0.05) -> Dict:
        if self.film_thickness is None:
            self.calculate_film_thickness()

        p = np.ones((self.n_theta, self.n_z)) * self.p_amb

        for iteration in range(max_iter):
            p_old = p.copy()

            residual = self._reynolds_residual(p, omega)

            h = self.film_thickness
            h3 = h ** 3
            dtheta = self.theta[1] - self.theta[0]
            dz = self.z[1] - self.z[0]

            coef_theta = h3 / (self.R ** 2 * dtheta ** 2)
            coef_z = h3 / (dz ** 2)
            diag = 2 * (coef_theta + coef_z)

            p_new = (p_old - relaxation * residual / diag)

            p_new[:, 0] = self.p_amb
            p_new[:, -1] = self.p_amb
            p_new[0, :] = p_new[-1, :]

            p = np.maximum(p_new, self.p_amb * 0.01)

            error = np.linalg.norm(p - p_old) / (np.linalg.norm(p_old) + 1e-10)
            if error < tol:
                break

        self.pressure = p

        dtheta = self.theta[1] - self.theta[0]
        dz = self.z[1] - self.z[0]
        load_capacity_z = -_trapz(_trapz(p * np.cos(self.Theta), self.z, axis=1), self.theta) * self.R
        load_capacity_x = _trapz(_trapz(p * np.sin(self.Theta), self.z, axis=1), self.theta) * self.R
        load_capacity = np.sqrt(load_capacity_z ** 2 + load_capacity_x ** 2)

        attitude_angle = np.arctan2(load_capacity_x, -load_capacity_z)

        return {
            'pressure': self.pressure,
            'film_thickness': self.film_thickness,
            'load_capacity': load_capacity,
            'attitude_angle': attitude_angle,
            'max_pressure': np.max(self.pressure),
            'min_pressure': np.min(self.pressure),
            'iterations': iteration + 1,
            'converged': error < tol,
        }

    def calculate_velocity_field(self, omega: float) -> Dict:
        if self.film_thickness is None:
            self.calculate_film_thickness()
        if self.pressure is None:
            self.solve_pressure(omega)

        h = self.film_thickness
        R = self.R
        mu = self.mu

        dtheta = self.theta[1] - self.theta[0]
        dz = self.z[1] - self.z[0]

        dp_dtheta = np.gradient(self.pressure, dtheta, axis=0) / R
        dp_dz = np.gradient(self.pressure, dz, axis=1)

        u_surface = omega * R

        y_normalized = np.linspace(0, 1, 20)
        u_profile = np.zeros((self.n_theta, self.n_z, len(y_normalized)))
        v_profile = np.zeros((self.n_theta, self.n_z, len(y_normalized)))

        for i, y_norm in enumerate(y_normalized):
            y = y_norm * h
            u_profile[:, :, i] = u_surface * (1 - y / h) + (y * (y - h) / (2 * mu * R)) * dp_dtheta
            v_profile[:, :, i] = (y * (y - h) / (2 * mu)) * dp_dz

        self.velocity = {
            'u': u_profile,
            'v': v_profile,
            'y_normalized': y_normalized,
        }

        return self.velocity

    def get_pressure_distribution_1d(self) -> Dict:
        mid_z_idx = self.n_z // 2
        return {
            'theta': self.theta,
            'pressure': self.pressure[:, mid_z_idx],
            'film_thickness': self.film_thickness[:, mid_z_idx],
        }

    def update_parameters(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.calculate_film_thickness()
