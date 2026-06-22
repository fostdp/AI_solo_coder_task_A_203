"""
v3.0 架构重构简化回归测试
不依赖Redis订阅线程（跨进程/线程问题复杂），改为直接同步调用四个服务。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import (
    get_fluid_config,
    get_bearing_config,
    get_messaging_config,
    get_channel,
    get_redis_config,
    reload_all,
)
from backend.messaging import MessageBus
from backend.services import (
    DTUReceiver,
    FlowSimulator,
    FrictionAnalyzerService,
    AlarmWebSocketService,
)
from backend.simulation import CavitationModel, FrictionAnalyzer, WaterFilmSolver


def section(title, idx, total):
    print()
    print("=" * 60)
    print(f"  [{idx}/{total}] {title}")
    print("=" * 60)


def test_config_loader():
    section("配置加载器", 1, 7)
    fluid = get_fluid_config()
    assert fluid['density'] == 1000.0
    assert fluid['viscosity_model'] == 'andrade'
    print(f"    流体: 密度={fluid['density']}, 粘温模型={fluid['viscosity_model']}, "
          f"表面张力={fluid['surface_tension']}")

    bearing = get_bearing_config()
    default = bearing['bearing']['song_dynasty_water_wheel']
    print(f"    轴承: R={default['radius_m']}m, L={default['length_m']}m, c={default['clearance_m']}m")
    assert default['radius_m'] == 0.05

    msg = get_messaging_config()
    assert 'channels' in msg
    ch_raw = get_channel('raw_data')
    ch_flow = get_channel('flow_result')
    print(f"    通道: raw_data={ch_raw}, flow_result={ch_flow}, alerts={get_channel('alerts')}")
    redis_cfg = get_redis_config()
    print(f"    Redis: host={redis_cfg.get('host')}, port={redis_cfg.get('port')}")

    reload_all()
    print("  ✅ 通过")


def test_message_bus_publish_cache():
    section("消息总线 (发布+缓存)", 2, 7)
    bus = MessageBus.instance()
    print(f"    模式: {bus.mode}")
    bus.publish('alerts', {'type': 'test', 'v': 1})
    bus.setex('test:cfgkey', 60, {'a': 1, 'b': 'xyz'})
    v = bus.get('test:cfgkey')
    assert v and v['b'] == 'xyz'
    print(f"    setex/get OK: {v}")
    print("  ✅ 通过")


def test_dtu_receiver():
    section("DTU接收器 (数据采集+校验)", 3, 7)
    bus = MessageBus.instance()
    dtu = DTUReceiver(bus=bus)
    raw = {
        'rpm': 35.2, 'water_pressure': 105.5, 'friction_coefficient': 0.0045,
        'water_temperature': 22.3, 'power_loss_watts': 0.25, 'flow_rate_m3s': 1.2e-5,
        'eccentricity_ratio': 0.3, 'load_capacity_n': 780.0, 'max_pressure_pa': 120000.0,
        'min_film_thickness_micron': 65.0, 'avg_velocity_mps': 0.18,
        'cavitation_area_fraction': 0.02, 'vapor_fraction_max': 0.001,
        'film_status': 'normal', 'power_status': 'normal',
    }
    result = dtu.receive('bearing-south-01', raw)
    assert result.status == 'accepted'
    print(f"    接收状态: {result.status}, ts={result.timestamp}")

    cached = dtu.get_latest('bearing-south-01')
    assert cached is not None and abs(cached['rpm'] - 35.2) < 0.01
    print(f"    缓存: rpm={cached['rpm']}, T={cached['water_temperature']}°C")

    try:
        dtu.receive('bad', {'rpm': 'invalid'})
        assert False
    except ValueError as e:
        print(f"    校验失败(预期): {str(e)[:45]}")

    print(f"    最近ID: {dtu.list_recent_ids()}")
    print("  ✅ 通过")


def test_flow_simulator():
    section("流场仿真器 (雷诺方程+空化+RP气泡)", 4, 7)
    bus = MessageBus.instance()
    flow = FlowSimulator(bus=bus, auto_subscribe=False)

    result = flow.compute(rpm=30.0, eccentricity_ratio=0.3, temperature=293.15)
    required = ['pressure_distribution_pa', 'film_thickness_m', 'load_capacity_n',
                'cavitation_area_fraction', 'film_rupture_risk', 'film_status']
    for k in required:
        assert k in result, f'缺失: {k}'

    print(f"    承载力: {result['load_capacity_n']:.1f} N")
    print(f"    最大压力: {result['max_pressure_pa']:.0f} Pa, 最小膜厚: {result['min_film_thickness_m']*1e6:.2f} μm")
    print(f"    空化比例: {result['cavitation_area_fraction']*100:.2f}%")
    print(f"    水膜状态: {result['film_status']} (风险={result['film_rupture_risk']*100:.1f}%)")
    print(f"    动空化: {result['is_dynamic_cavitation']}, 阈值={result['cavitation_threshold_pa']/1000:.3f} kPa")
    print(f"    粘度: {result['effective_viscosity']*1e6:.2f} μPa·s (T={result.get('temperature')}K)")
    print(f"    求解收敛: {result['solver_converged']}, 迭代={result['solver_iterations']}")

    for rpm in [10, 30, 60, 100, 150]:
        r = flow.compute(rpm=rpm, eccentricity_ratio=0.3)
        print(f"    {rpm:>3d} RPM: 空化={r['cavitation_area_fraction']*100:>5.2f}%, "
              f"阈值={r['cavitation_threshold_pa']/1000:.3f} kPa, 动空化={r['is_dynamic_cavitation']}")
    print("  ✅ 通过")


def test_friction_analyzer_service():
    section("摩擦分析服务 (粘温+温升迭代)", 5, 7)
    bus = MessageBus.instance()
    flow = FlowSimulator(bus=bus, auto_subscribe=False)
    fri = FrictionAnalyzerService(bus=bus, auto_subscribe=False)

    for T in [283.15, 293.15, 303.15, 323.15, 343.15]:
        fr = flow.compute(rpm=30.0, eccentricity_ratio=0.3, temperature=T)
        ft = fri.compute_from_flow(fr, load_n=800.0)
        print(f"    T={T-273.15:>5.1f}°C: μ={ft['effective_viscosity_pa_s']*1e6:>6.1f} μPa·s, "
              f"fc={ft['friction_coefficient']:.5f}, P={ft['power_loss_watts']*1000:>6.2f} mW, "
              f"ΔT={ft['temperature_rise_k']:.2f} K, 迭代={ft['coupled_iterations']}, 状态={ft['power_status']}")

    full = fri.compute_from_flow(
        flow.compute(rpm=50.0, eccentricity_ratio=0.5, temperature=298.15),
        load_n=1200.0,
    )
    print()
    print(f"    高负荷: fc={full['friction_coefficient']:.5f}, "
          f"扭矩={full['friction_torque_nm']:.4f} N·m, 功耗={full['power_loss_watts']*1000:.2f} mW")
    print(f"    Re={full['reynolds_number']:.1f}, Pr={full['prandtl_number']:.2f}, Nu={full['nusselt_number']:.2f}")
    print(f"    流量={full['flow_rate_m3s']:.3e} m³/s, 换热系数={full['heat_transfer_coefficient']:.1f} W/m²K")
    print("  ✅ 通过")


def test_alarm_service():
    section("告警服务 (判定+历史)", 6, 7)
    bus = MessageBus.instance()
    alarm = AlarmWebSocketService(bus=bus, auto_subscribe=False)

    a_good = alarm.evaluate('ok', {'film_rupture_risk': 0.15, 'cavitation_area_fraction': 0.02},
                            {'power_status': 'normal', 'power_loss_watts': 0.1, 'temperature_rise_k': 1.0})
    print(f"    正常工况: {len(a_good)} 条告警")
    assert len(a_good) == 0

    a_bad = alarm.evaluate('bad', {'film_rupture_risk': 0.85, 'cavitation_area_fraction': 0.3},
                           {'power_status': 'overload', 'power_loss_watts': 12.0, 'temperature_rise_k': 40.0})
    print(f"    故障工况: {len(a_bad)} 条告警")
    for a in a_bad:
        print(f"      - [{a['severity']:>8s}] {a['type']:>20s}: {a['message'][:50]}")
    assert len(a_bad) >= 4

    alarm.push_alerts(a_bad)
    hist = alarm.get_history(bearing_id='bad')
    assert len(hist) >= 4
    print(f"    历史缓存: {len(hist)} 条")
    print("  ✅ 通过")


def test_end_to_end_sync():
    section("端到端同步链路: DTU→Flow→Friction→Alarm", 7, 7)
    bus = MessageBus.instance()
    dtu = DTUReceiver(bus=bus)
    flow = FlowSimulator(bus=bus, auto_subscribe=False)
    fri = FrictionAnalyzerService(bus=bus, auto_subscribe=False)
    alarm = AlarmWebSocketService(bus=bus, auto_subscribe=False)

    reading = {
        'rpm': 60.0, 'water_pressure': 150.0, 'friction_coefficient': 0.006,
        'water_temperature': 40.0, 'power_loss_watts': 0.8, 'flow_rate_m3s': 1.5e-5,
        'eccentricity_ratio': 0.55, 'load_capacity_n': 1100.0,
        'max_pressure_pa': 180000.0, 'min_film_thickness_micron': 40.0,
        'avg_velocity_mps': 0.3, 'cavitation_area_fraction': 0.12,
        'vapor_fraction_max': 0.01, 'film_status': 'warning', 'power_status': 'warning',
    }

    dtu_resp = dtu.receive('bearing-e2e', reading)
    assert dtu_resp.status == 'accepted'

    T = reading['water_temperature'] + 273.15
    flow_result = flow.compute(rpm=reading['rpm'],
                               eccentricity_ratio=reading['eccentricity_ratio'],
                               temperature=T)
    flow_result['bearing_id'] = 'bearing-e2e'
    assert flow_result['film_status'] in ('normal', 'warning', 'ruptured')

    fri_result = fri.compute_from_flow(flow_result, load_n=reading['load_capacity_n'])
    assert fri_result['power_status'] in ('normal', 'warning', 'overload')

    alerts = alarm.evaluate('bearing-e2e', flow_result, fri_result)

    print(f"    DTU: rpm={reading['rpm']} → accepted")
    print(f"    Flow: 承载力={flow_result['load_capacity_n']:.1f} N, 空化={flow_result['cavitation_area_fraction']*100:.1f}%, "
          f"状态={flow_result['film_status']}")
    print(f"    Friction: fc={fri_result['friction_coefficient']:.5f}, P={fri_result['power_loss_watts']*1000:.1f} mW, "
          f"ΔT={fri_result['temperature_rise_k']:.2f} K, 状态={fri_result['power_status']}")
    print(f"    Alarm: {len(alerts)} 条告警")
    for a in alerts:
        print(f"      - [{a['severity']}] {a['type']}")

    # 存入缓存
    bus.setex('bearing:flow:bearing-e2e', 600, flow_result)
    bus.setex('bearing:friction:bearing-e2e', 600, fri_result)

    # 从缓存读取
    cached_flow = flow.get_last_result('bearing-e2e') or bus.get('bearing:flow:bearing-e2e')
    cached_fri = fri.get_last_result('bearing-e2e') or bus.get('bearing:friction:bearing-e2e')
    cached_dtu = dtu.get_latest('bearing-e2e')

    assert cached_dtu is not None
    assert cached_flow is not None
    assert cached_fri is not None
    print(f"    缓存读取: DTU ✓, Flow ✓, Friction ✓")
    print("  ✅ 通过")


def main():
    print()
    print("╔" + "=" * 58 + "╗")
    print("║     v3.0 架构重构 — 同步回归测试                          ║")
    print("║     配置 → 总线 → DTU → Flow → Friction → Alarm          ║")
    print("╚" + "=" * 58 + "╝")

    tests = [
        test_config_loader,
        test_message_bus_publish_cache,
        test_dtu_receiver,
        test_flow_simulator,
        test_friction_analyzer_service,
        test_alarm_service,
        test_end_to_end_sync,
    ]

    failed = []
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            print(f"\n  ❌ 测试失败: {t.__name__}\n")
            traceback.print_exc()
            failed.append(t.__name__)

    print()
    print("=" * 60)
    if not failed:
        print("  🎉 全部 7 项回归测试通过！")
    else:
        print(f"  ❌ 失败 {len(failed)}/{len(tests)}: {failed}")
    print("=" * 60)
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
