"""
水润滑轴承模拟器
模拟古代筒车轴承的传感器数据，每小时上报一次
基于Navier-Stokes方程和空化模型生成真实的物理数据
"""
import os
import sys
import time
import random
import math
from datetime import datetime
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.simulation import WaterFilmSolver, CavitationModel, FrictionAnalyzer


class BearingSimulator:
    def __init__(self, bearing_id: str = "bearing_001", api_url: str = "http://localhost:8000"):
        self.bearing_id = bearing_id
        self.api_url = api_url

        self.solver = WaterFilmSolver(
            bearing_radius=0.05,
            bearing_length=0.08,
            radial_clearance=2e-4,
            eccentricity=0.0,
            viscosity=1.002e-3,
        )
        self.cavitation = CavitationModel()
        self.friction = FrictionAnalyzer(
            bearing_radius=0.05,
            bearing_length=0.08,
            radial_clearance=2e-4,
        )

        self.base_rpm = 35.0
        self.load = 800.0
        self.supply_temp = 20.0 + 273.15
        self.wear_factor = 0.0

        self.rpm_noise = 2.0
        self.temp_noise = 0.3

    def _update_temperature_dependent_properties(self, water_temp: float):
        temp_k = water_temp + 273.15
        mu_0 = 1.792e-3
        T0 = 273.15
        viscosity = mu_0 * math.exp(-1.8 * (temp_k - T0) / T0)
        self.solver.update_parameters(viscosity=viscosity)
        self.friction.mu = viscosity
        self.cavitation.update_temperature(temp_k)

    def generate_reading(self, time_hours: float = 0.0) -> dict:
        wear_increase = self.wear_factor * time_hours * 0.001

        rpm = self.base_rpm + 8 * math.sin(time_hours * 0.15) + random.gauss(0, self.rpm_noise)
        rpm = max(5.0, min(80.0, rpm))

        water_temp = 22.0 + 5 * math.sin(time_hours * 0.1) + random.gauss(0, self.temp_noise)
        water_temp = max(5.0, min(40.0, water_temp))

        base_eccentricity = 0.25 + wear_increase
        eccentricity_ratio = base_eccentricity + 0.1 * math.sin(time_hours * 0.2) + random.gauss(0, 0.02)
        eccentricity_ratio = max(0.05, min(0.95, eccentricity_ratio))

        self._update_temperature_dependent_properties(water_temp)

        eccentricity = eccentricity_ratio * self.solver.c
        self.solver.calculate_film_thickness(eccentricity)

        omega = rpm * 2 * math.pi / 60

        pressure_result = self.solver.solve_pressure(omega)
        pressure = pressure_result['pressure']
        film_thickness = pressure_result['film_thickness']

        cav_result = self.cavitation.detect_cavitation(pressure, film_thickness, omega)
        rupture_result = self.cavitation.assess_film_rupture(pressure, film_thickness, omega)

        load_capacity = pressure_result['load_capacity']
        actual_load = min(self.load, load_capacity * 0.8)

        friction_result = self.friction.full_analysis(
            omega=omega,
            load=actual_load,
            eccentricity_ratio=eccentricity_ratio,
            pressure_field=pressure,
            film_thickness=film_thickness,
            inlet_temp=self.supply_temp,
        )

        avg_pressure = float(pressure.mean())
        max_pressure = float(pressure.max())
        min_film = float(film_thickness.min())

        return {
            'rpm': float(rpm),
            'water_pressure': avg_pressure,
            'max_pressure': max_pressure,
            'friction_coefficient': friction_result['friction_coefficient'],
            'water_temperature': water_temp,
            'eccentricity_ratio': eccentricity_ratio,
            'min_film_thickness': min_film,
            'load_capacity': load_capacity,
            'friction_torque': friction_result['friction_torque'],
            'power_loss': friction_result['power_loss'],
            'sommerfeld_number': friction_result['sommerfeld_number'] if 'sommerfeld_number' in friction_result else 0.0,
            'temperature_rise': friction_result['temperature_rise'],
            'flow_rate': friction_result['flow_rate'],
            'cavitation_area_fraction': cav_result['cavitation_area_fraction'],
            'cavitation_max_vapor_fraction': cav_result['max_vapor_fraction'],
            'has_cavitation': cav_result['has_cavitation'],
            'rupture_risk': rupture_result['rupture_risk'],
            'film_status': rupture_result['status'],
            'power_status': friction_result['status'],
            'attitude_angle': pressure_result['attitude_angle'],
            'timestamp': datetime.utcnow().isoformat() + "Z",
        }

    def send_reading(self, data: dict) -> bool:
        try:
            url = f"{self.api_url}/api/bearing/{self.bearing_id}/data"
            response = requests.post(url, json=data, timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"  ⚠️  发送数据失败: {e}")
            return False

    def run_once(self, time_hours: float = 0.0) -> dict:
        data = self.generate_reading(time_hours)
        self._print_status(data)

        sent = self.send_reading(data)
        if sent:
            print(f"  ✅ 数据已发送至服务器")
        else:
            print(f"  ❌ 数据发送失败")

        return data

    def run_continuous(self, interval_seconds: int = 3600):
        print(f"\n🚀 轴承模拟器启动 - {self.bearing_id}")
        print(f"   上报间隔: {interval_seconds} 秒 ({interval_seconds / 3600:.1f} 小时)")
        print(f"   API地址: {self.api_url}")
        print("   按 Ctrl+C 停止\n")

        hour_counter = 0.0
        try:
            while True:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                      f"生成第 {hour_counter:.1f} 小时数据...")

                self.run_once(hour_counter)
                hour_counter += interval_seconds / 3600.0

                print(f"   等待 {interval_seconds} 秒...")
                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print(f"\n\n🛑 模拟器已停止，共运行 {hour_counter:.1f} 小时")

    def _print_status(self, data: dict):
        status_icon = "✅" if data['film_status'] == 'normal' else (
            "⚠️" if data['film_status'] == 'warning' else "❌"
        )
        power_icon = "✅" if data['power_status'] == 'normal' else (
            "⚠️" if data['power_status'] == 'warning' else "❌"
        )

        print(f"   转速: {data['rpm']:.1f} RPM")
        print(f"   水温: {data['water_temperature']:.1f} °C")
        print(f"   平均压力: {data['water_pressure'] / 1000:.1f} kPa")
        print(f"   摩擦系数: {data['friction_coefficient']:.6f}")
        print(f"   偏心率: {data['eccentricity_ratio']:.3f}")
        print(f"   最小水膜厚度: {data['min_film_thickness'] * 1e6:.1f} μm")
        print(f"   摩擦功耗: {data['power_loss']:.2f} W")
        print(f"   水膜状态: {status_icon} {data['film_status']}")
        print(f"   功耗状态: {power_icon} {data['power_status']}")
        if data['has_cavitation']:
            print(f"   空化面积比: {data['cavitation_area_fraction'] * 100:.1f}%")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='水润滑轴承模拟器')
    parser.add_argument('--bearing-id', default='bearing_001', help='轴承ID')
    parser.add_argument('--api-url', default='http://localhost:8000', help='API地址')
    parser.add_argument('--interval', type=int, default=3600, help='上报间隔（秒）')
    parser.add_argument('--once', action='store_true', help='只运行一次')
    parser.add_argument('--fast', type=int, default=0,
                        help='快速模式，生成指定小时数的数据，每1秒模拟1小时')

    args = parser.parse_args()

    simulator = BearingSimulator(bearing_id=args.bearing_id, api_url=args.api_url)

    if args.once:
        simulator.run_once(0.0)
    elif args.fast > 0:
        print(f"\n⚡ 快速模式: 模拟 {args.fast} 小时的数据")
        for i in range(args.fast):
            print(f"\n--- 第 {i} 小时 ---")
            data = simulator.generate_reading(float(i))
            simulator._print_status(data)
            simulator.send_reading(data)
            time.sleep(0.1)
        print(f"\n✅ 完成 {args.fast} 小时数据模拟")
    else:
        simulator.run_continuous(interval_seconds=args.interval)


if __name__ == '__main__':
    main()
