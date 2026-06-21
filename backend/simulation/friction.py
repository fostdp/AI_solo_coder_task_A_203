import numpy as np
from typing import Dict, Optional, Tuple


def _trapz(y, x=None, dx=1.0, axis=-1):
    if hasattr(np, 'trapezoid'):
        if x is not None:
            return np.trapezoid(y, x, axis=axis)
        return np.trapezoid(y, dx=dx, axis=axis)
    if x is not None:
        return np.trapz(y, x, axis=axis)
    return np.trapz(y, dx=dx, axis=axis)


class ViscosityTemperatureModel:
    def __init__(self, model_type: str = 'andrade'):
        self.model_type = model_type

        self.water_params = {
            'andrade': {'A': 1.856e-6, 'B': 1948.0, 'T0': 273.15},
            'reynolds': {'mu0': 1.792e-3, 'beta': 0.025, 'T0': 273.15},
            'walther': {'A': 10.2, 'B': 1.25, 'nu0': 1.792e-6},
            'vogel': {'mu0': 1.002e-3, 'B': 578.0, 'T_inf': 138.0},
            'polynomial': {
                'coeffs': [
                    1.7913989e-3,
                    -5.8231280e-5,
                    1.1361195e-6,
                    -1.3306660e-8,
                    9.5541671e-11,
                    -4.2670126e-13,
                    1.1081089e-15,
                    -1.6222585e-18,
                    1.0452325e-21,
                ],
                'T0': 273.15,
            },
        }

        self.params = self.water_params[model_type]

    def calculate_viscosity(self, T: float) -> float:
        if self.model_type == 'andrade':
            return self._andrade(T)
        elif self.model_type == 'reynolds':
            return self._reynolds(T)
        elif self.model_type == 'walther':
            return self._walther(T)
        elif self.model_type == 'vogel':
            return self._vogel(T)
        elif self.model_type == 'polynomial':
            return self._polynomial(T)
        else:
            return self._andrade(T)

    def _andrade(self, T: float) -> float:
        A = self.params['A']
        B = self.params['B']
        return A * np.exp(B / T)

    def _reynolds(self, T: float) -> float:
        mu0 = self.params['mu0']
        beta = self.params['beta']
        T0 = self.params['T0']
        return mu0 * np.exp(-beta * (T - T0))

    def _walther(self, T: float) -> float:
        A = self.params['A']
        B = self.params['B']
        rho = 1000.0

        log_log_nu = A - B * np.log10(T)
        nu = 10 ** (10 ** log_log_nu - 0.8) - 0.8e-6
        nu = max(nu, 1e-7)

        return nu * rho

    def _vogel(self, T: float) -> float:
        mu0 = self.params['mu0']
        B = self.params['B']
        T_inf = self.params['T_inf']
        return mu0 * np.exp(B / (T - T_inf))

    def _polynomial(self, T: float) -> float:
        coeffs = self.params['coeffs']
        T0 = self.params['T0']
        dT = T - T0

        mu = 0.0
        for i, c in enumerate(coeffs):
            mu += c * (dT ** i)

        return max(mu, 1e-4)

    def calculate_derivative(self, T: float, dT: float = 0.01) -> float:
        mu1 = self.calculate_viscosity(T - dT)
        mu2 = self.calculate_viscosity(T + dT)
        return (mu2 - mu1) / (2 * dT)


class TemperatureDependentFriction:
    def __init__(
        self,
        bearing_radius: float = 0.05,
        bearing_length: float = 0.08,
        radial_clearance: float = 2e-4,
        viscosity_model: str = 'andrade',
        reference_temp: float = 293.15,
    ):
        self.R = bearing_radius
        self.L = bearing_length
        self.c = radial_clearance
        self.T_ref = reference_temp

        self.visc_model = ViscosityTemperatureModel(model_type=viscosity_model)
        self.mu_ref = self.visc_model.calculate_viscosity(reference_temp)

        self.temperature_field = None
        self.viscosity_field = None

    def initialize_temperature_field(self, n_theta: int = 64, n_z: int = 32):
        theta = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
        z = np.linspace(-self.L / 2, self.L / 2, n_z)
        Theta, Z = np.meshgrid(theta, z, indexing='ij')
        self.temperature_field = np.ones_like(Theta) * self.T_ref
        self.viscosity_field = np.ones_like(Theta) * self.mu_ref

    def update_temperature_field(
        self,
        omega: float,
        pressure_field: np.ndarray,
        film_thickness: np.ndarray,
        inlet_temp: float,
        heat_transfer_coeff: float = 100.0,
        wall_temp: Optional[float] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        if self.temperature_field is None:
            n_theta, n_z = pressure_field.shape
            self.initialize_temperature_field(n_theta, n_z)

        h = film_thickness
        mu = self.viscosity_field if self.viscosity_field is not None else self.mu_ref

        u_surface = omega * self.R
        viscous_dissipation = mu * (u_surface / h) ** 2

        dtheta = 2 * np.pi / pressure_field.shape[0]
        dz = self.L / pressure_field.shape[1]

        dp_dtheta = np.gradient(pressure_field, dtheta, axis=0) / self.R

        couette_flow = 0.5 * u_surface * h
        pressure_flow = -h ** 3 / (12 * mu) * dp_dtheta
        total_flow = couette_flow + pressure_flow

        rho = 1000.0
        c_p = 4186.0
        k_water = 0.6

        dT_dx = np.gradient(self.temperature_field, dtheta * self.R, axis=0)
        d2T_dx2 = np.gradient(dT_dx, dtheta * self.R, axis=0)
        d2T_dz2 = np.gradient(np.gradient(self.temperature_field, dz, axis=1), dz, axis=1)

        convection = rho * c_p * total_flow * dT_dx
        diffusion = k_water * (d2T_dx2 + d2T_dz2)

        dT_dt = (viscous_dissipation + diffusion - convection) / (rho * c_p)

        if wall_temp is not None:
            boundary_heat = heat_transfer_coeff * (wall_temp - self.temperature_field) * 2 / h
            dT_dt += boundary_heat / (rho * c_p)

        dt_stable = 0.01
        self.temperature_field = np.clip(
            self.temperature_field + dT_dt * dt_stable,
            inlet_temp,
            inlet_temp + 50.0,
        )

        self.temperature_field[:, 0] = inlet_temp
        self.temperature_field[:, -1] = inlet_temp

        self.viscosity_field = np.vectorize(self.visc_model.calculate_viscosity)(
            self.temperature_field
        )

        avg_mu = np.mean(self.viscosity_field)
        avg_T = np.mean(self.temperature_field)

        return self.temperature_field, self.viscosity_field

    def get_effective_viscosity(self) -> float:
        if self.viscosity_field is None:
            return self.mu_ref
        return float(np.mean(self.viscosity_field))

    def get_average_temperature(self) -> float:
        if self.temperature_field is None:
            return self.T_ref
        return float(np.mean(self.temperature_field))


class FrictionAnalyzer:
    def __init__(
        self,
        bearing_radius: float = 0.05,
        bearing_length: float = 0.08,
        radial_clearance: float = 2e-4,
        viscosity: float = 1.002e-3,
        density: float = 1000.0,
        specific_heat: float = 4186.0,
        viscosity_model: str = 'andrade',
        reference_temp: float = 293.15,
    ):
        self.R = bearing_radius
        self.L = bearing_length
        self.c = radial_clearance
        self.mu = viscosity
        self.rho = density
        self.c_p = specific_heat

        self.temp_friction = TemperatureDependentFriction(
            bearing_radius=bearing_radius,
            bearing_length=bearing_length,
            radial_clearance=radial_clearance,
            viscosity_model=viscosity_model,
            reference_temp=reference_temp,
        )

        self.temperature_correction_factor = 1.0
        self.last_viscosity = viscosity
        self.last_temperature = reference_temp

    def calculate_viscosity_temperature_correction(
        self,
        temperature: float,
        model_type: Optional[str] = None,
    ) -> Dict:
        if model_type is not None:
            self.temp_friction.visc_model = ViscosityTemperatureModel(model_type=model_type)

        mu_T = self.temp_friction.visc_model.calculate_viscosity(temperature)
        dmu_dT = self.temp_friction.visc_model.calculate_derivative(temperature)
        correction_factor = mu_T / self.mu

        self.last_viscosity = mu_T
        self.last_temperature = temperature
        self.temperature_correction_factor = correction_factor

        return {
            'viscosity': mu_T,
            'reference_viscosity': self.mu,
            'correction_factor': correction_factor,
            'dmu_dT': dmu_dT,
            'temperature': temperature,
            'model': self.temp_friction.visc_model.model_type,
        }

    def calculate_friction_coefficient(
        self,
        omega: float,
        eccentricity_ratio: float,
        sommerfeld_number: Optional[float] = None,
        temperature: Optional[float] = None,
        viscosity_model: Optional[str] = None,
    ) -> Dict:
        mu_eff = self.mu

        if temperature is not None:
            temp_result = self.calculate_viscosity_temperature_correction(
                temperature, viscosity_model
            )
            mu_eff = temp_result['viscosity']
            correction_factor = temp_result['correction_factor']
        else:
            correction_factor = 1.0

        if sommerfeld_number is None:
            sommerfeld_number = (mu_eff * omega * self.R / (self.c ** 2)) * (
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

        temp_correction = 1.0 + 0.15 * (correction_factor - 1.0)
        friction_coeff = f_Rc * (self.c / self.R) * temp_correction

        return {
            'friction_coefficient': friction_coeff,
            'sommerfeld_number': sommerfeld_number,
            'f_Rc': f_Rc,
            'effective_viscosity': mu_eff,
            'temperature_correction_factor': correction_factor,
            'temperature': temperature,
        }

    def calculate_friction_torque(
        self,
        omega: float,
        load: float,
        eccentricity_ratio: float,
        pressure_field: Optional[np.ndarray] = None,
        film_thickness: Optional[np.ndarray] = None,
        temperature: Optional[float] = None,
        viscosity_model: Optional[str] = None,
    ) -> Dict:
        friction_result = self.calculate_friction_coefficient(
            omega, eccentricity_ratio, temperature=temperature,
            viscosity_model=viscosity_model
        )
        f = friction_result['friction_coefficient']
        mu_eff = friction_result['effective_viscosity']

        torque_coulomb = f * load * self.R

        if pressure_field is not None and film_thickness is not None:
            torque_shear = self._calculate_shear_torque(
                pressure_field, film_thickness, omega, mu_eff
            )
        else:
            torque_shear = torque_coulomb * 0.8

        total_torque = torque_shear + torque_coulomb * 0.2

        if temperature is not None:
            T_correction = 1.0 - 0.002 * (temperature - 293.15)
            T_correction = max(0.7, min(T_correction, 1.3))
            total_torque = total_torque * T_correction

        return {
            'friction_torque': total_torque,
            'shear_torque': torque_shear,
            'coulomb_torque': torque_coulomb,
            'friction_coefficient': f,
            'effective_viscosity': mu_eff,
            'temperature': temperature,
        }

    def _calculate_shear_torque(
        self,
        pressure: np.ndarray,
        film_thickness: np.ndarray,
        omega: float,
        viscosity: Optional[float] = None,
    ) -> float:
        h = film_thickness
        mu = viscosity if viscosity is not None else self.mu
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
        temperature: Optional[float] = None,
        viscosity_model: Optional[str] = None,
        iteratively_update_temp: bool = False,
    ) -> Dict:
        if iteratively_update_temp and temperature is not None:
            result = self._iterate_temperature_power(
                omega, load, eccentricity_ratio,
                pressure_field, film_thickness,
                temperature, viscosity_model
            )
            return result

        torque_result = self.calculate_friction_torque(
            omega, load, eccentricity_ratio,
            pressure_field, film_thickness,
            temperature, viscosity_model
        )

        power_loss = torque_result['friction_torque'] * omega

        return {
            'power_loss': power_loss,
            'friction_torque': torque_result['friction_torque'],
            'shear_torque': torque_result['shear_torque'],
            'coulomb_torque': torque_result['coulomb_torque'],
            'friction_coefficient': torque_result['friction_coefficient'],
            'effective_viscosity': torque_result['effective_viscosity'],
            'temperature': temperature,
            'temperature_correction_applied': temperature is not None,
        }

    def _iterate_temperature_power(
        self,
        omega: float,
        load: float,
        eccentricity_ratio: float,
        pressure_field: Optional[np.ndarray],
        film_thickness: Optional[np.ndarray],
        inlet_temp: float,
        viscosity_model: Optional[str] = None,
        max_iter: int = 20,
        tol: float = 0.01,
    ) -> Dict:
        T_current = inlet_temp
        T_prev = T_current
        power_prev = 0.0

        for iteration in range(max_iter):
            torque_result = self.calculate_friction_torque(
                omega, load, eccentricity_ratio,
                pressure_field, film_thickness,
                T_current, viscosity_model
            )

            power_loss = torque_result['friction_torque'] * omega

            flow_result = self.calculate_flow_rate(omega, eccentricity_ratio)
            flow_rate = flow_result['flow_rate']

            if flow_rate > 0:
                dT = power_loss / (self.rho * self.c_p * flow_rate)
            else:
                dT = 10.0

            T_current = inlet_temp + dT * 0.5

            power_error = abs(power_loss - power_prev) / (power_loss + 1e-10)
            temp_error = abs(T_current - T_prev)

            if power_error < tol and temp_error < 0.1:
                break

            power_prev = power_loss
            T_prev = T_current

        return {
            'power_loss': power_loss,
            'friction_torque': torque_result['friction_torque'],
            'shear_torque': torque_result['shear_torque'],
            'coulomb_torque': torque_result['coulomb_torque'],
            'friction_coefficient': torque_result['friction_coefficient'],
            'effective_viscosity': torque_result['effective_viscosity'],
            'inlet_temperature': inlet_temp,
            'outlet_temperature': T_current,
            'temperature_rise': T_current - inlet_temp,
            'iterations': iteration + 1,
            'converged': power_error < tol,
            'temperature_correction_applied': True,
        }

    def calculate_heat_generation(
        self,
        power_loss: float,
        flow_rate: float,
        inlet_temp: float = 293.15,
        thermal_conductivity: float = 0.6,
    ) -> Dict:
        temp_rise = power_loss / (self.rho * self.c_p * flow_rate) if flow_rate > 0 else float('inf')
        outlet_temp = inlet_temp + temp_rise

        area = 2 * np.pi * self.R * self.L
        heat_flux = power_loss / area

        reynolds = self.rho * flow_rate / (self.L * self.last_viscosity) if flow_rate > 0 else 0
        prandtl = self.c_p * self.last_viscosity / thermal_conductivity
        nusselt = 0.664 * np.sqrt(max(reynolds, 1)) * (prandtl ** (1/3)) if reynolds > 0 else 0
        h_conv = nusselt * thermal_conductivity / self.L if reynolds > 0 else 10

        return {
            'temperature_rise': temp_rise,
            'outlet_temperature': outlet_temp,
            'inlet_temperature': inlet_temp,
            'heat_flux': heat_flux,
            'reynolds_number': reynolds,
            'prandtl_number': prandtl,
            'nusselt_number': nusselt,
            'heat_transfer_coeff': h_conv,
        }

    def calculate_flow_rate(
        self,
        omega: float,
        eccentricity_ratio: float,
        supply_pressure: float = 101325.0,
        ambient_pressure: float = 101325.0,
        viscosity: Optional[float] = None,
    ) -> Dict:
        mu = viscosity if viscosity is not None else self.last_viscosity
        epsilon = eccentricity_ratio
        h_avg = self.c * (1 + epsilon ** 2 / 2)

        q_couette = np.pi * self.R * omega * self.c * (1 - epsilon)

        delta_p = supply_pressure - ambient_pressure
        q_poiseuille = (np.pi * self.R * h_avg ** 3 * delta_p) / (6 * mu * self.L)

        total_flow = q_couette + q_poiseuille

        return {
            'flow_rate': total_flow,
            'couette_flow': q_couette,
            'poiseuille_flow': q_poiseuille,
            'effective_viscosity': mu,
        }

    def assess_power_warning(
        self,
        power_loss: float,
        max_power: float = 500.0,
        warning_threshold: float = 0.7,
        temperature: Optional[float] = None,
    ) -> Dict:
        power_ratio = power_loss / max_power

        is_overload = power_ratio > 1.0
        is_warning = power_ratio > warning_threshold

        temp_factor = 1.0
        if temperature is not None:
            if temperature > 313.15:
                temp_factor = 1.2
                is_warning = is_warning or True
            if temperature > 333.15:
                temp_factor = 1.5
                is_overload = True

        return {
            'power_loss': power_loss,
            'max_power': max_power,
            'power_ratio': power_ratio,
            'temperature_factor': temp_factor,
            'temperature': temperature,
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
        viscosity_model: str = 'andrade',
        iterate_temperature: bool = True,
    ) -> Dict:
        power_result = self.calculate_power_loss(
            omega, load, eccentricity_ratio,
            pressure_field, film_thickness,
            temperature=inlet_temp,
            viscosity_model=viscosity_model,
            iteratively_update_temp=iterate_temperature,
        )

        effective_mu = power_result.get('effective_viscosity', self.mu)

        flow_result = self.calculate_flow_rate(
            omega, eccentricity_ratio, supply_pressure,
            viscosity=effective_mu,
        )

        outlet_temp = power_result.get('outlet_temperature', inlet_temp)

        heat_result = self.calculate_heat_generation(
            power_result['power_loss'], flow_result['flow_rate'], inlet_temp
        )

        warning_result = self.assess_power_warning(
            power_result['power_loss'], max_power,
            temperature=outlet_temp,
        )

        return {
            **power_result,
            **flow_result,
            **heat_result,
            **warning_result,
            'eccentricity_ratio': eccentricity_ratio,
            'rotational_speed_rpm': omega * 60 / (2 * np.pi),
            'viscosity_model': viscosity_model,
        }

    def update_viscosity(self, temperature: float, model_type: str = 'andrade'):
        result = self.calculate_viscosity_temperature_correction(temperature, model_type)
        self.mu = result['viscosity']
        return self.mu

    def compare_viscosity_models(self, temperature: float) -> Dict:
        models = ['andrade', 'reynolds', 'walther', 'vogel', 'polynomial']
        results = {}

        for model in models:
            visc_model = ViscosityTemperatureModel(model_type=model)
            results[model] = visc_model.calculate_viscosity(temperature)

        return results
