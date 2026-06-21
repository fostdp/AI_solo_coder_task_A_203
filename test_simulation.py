"""
测试脚本 - 验证水润滑流场仿真模型
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from simulation import WaterFilmSolver, CavitationModel, FrictionAnalyzer
import numpy as np


def test_water_film_solver():
    print("测试水膜求解器 (Navier-Stokes/雷诺方程)...")
    solver = WaterFilmSolver(grid_size=32)
    solver.calculate_film_thickness(0.3 * solver.c)
    result = solver.solve_pressure(30 * 2 * np.pi / 60)

    print(f"  最大压力: {result['max_pressure']/1000:.2f} kPa")
    print(f"  最小压力: {result['min_pressure']/1000:.2f} kPa")
    print(f"  承载能力: {result['load_capacity']:.2f} N")
    print(f"  偏位角: {result['attitude_angle']*180/np.pi:.2f}°")
    print(f"  迭代次数: {result['iterations']}")
    print(f"  收敛: {result['converged']}")

    velocity = solver.calculate_velocity_field(30 * 2 * np.pi / 60)
    print(f"  速度场计算完成: u.shape={velocity['u'].shape}")
    print()

    return result


def test_cavitation_model(pressure, film_thickness):
    print("测试空化模型...")
    cav = CavitationModel()
    cav_result = cav.detect_cavitation(pressure, film_thickness)

    print(f"  空化面积比: {cav_result['cavitation_area_fraction']:.4f}")
    print(f"  最大蒸汽体积分数: {cav_result['max_vapor_fraction']:.4f}")
    print(f"  有空化: {cav_result['has_cavitation']}")

    rupture = cav.assess_film_rupture(pressure, film_thickness)
    print(f"  最小水膜厚度: {rupture['min_film_thickness']*1e6:.1f} μm")
    print(f"  破裂风险: {rupture['rupture_risk']:.2f}")
    print(f"  水膜状态: {rupture['status']}")

    p_corrected = cav.apply_cavitation_correction(pressure, film_thickness)
    print(f"  空化修正后压力范围: {p_corrected.min()/1000:.2f} ~ {p_corrected.max()/1000:.2f} kPa")

    cav.update_temperature(300)
    print(f"  300K时饱和蒸气压: {cav.p_vap:.2f} Pa")
    print()


def test_friction_analyzer(pressure, film_thickness):
    print("测试摩擦功耗分析...")
    friction = FrictionAnalyzer()

    omega = 30 * 2 * np.pi / 60
    fric_result = friction.full_analysis(
        omega=omega,
        load=500,
        eccentricity_ratio=0.3,
        pressure_field=pressure,
        film_thickness=film_thickness,
    )

    print(f"  摩擦系数: {fric_result['friction_coefficient']:.6f}")
    print(f"  摩擦力矩: {fric_result['friction_torque']:.4f} N·m")
    print(f"  切向力矩: {fric_result['shear_torque']:.4f} N·m")
    print(f"  库仑力矩: {fric_result['coulomb_torque']:.4f} N·m")
    print(f"  摩擦功耗: {fric_result['power_loss']:.3f} W")
    print(f"  流量: {fric_result['flow_rate']*1e6:.2f} mL/s")
    print(f"  温升: {fric_result['temperature_rise']:.3f} K")
    print(f"  功耗状态: {fric_result['status']}")

    warning = friction.assess_power_warning(fric_result['power_loss'], max_power=500)
    print(f"  功耗占比: {warning['power_ratio']*100:.1f}%")

    mu = friction.update_viscosity(300)
    print(f"  300K时粘度: {mu*1e6:.1f} μPa·s")
    print()


def main():
    print("=" * 60)
    print("  水润滑流场仿真模型 - 单元测试")
    print("=" * 60)
    print()

    try:
        solver_result = test_water_film_solver()
        test_cavitation_model(solver_result['pressure'], solver_result['film_thickness'])
        test_friction_analyzer(solver_result['pressure'], solver_result['film_thickness'])

        print("=" * 60)
        print("  ✅ 所有测试通过！")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
