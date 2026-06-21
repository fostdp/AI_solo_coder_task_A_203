"""
InfluxDB 初始化脚本
用于创建古代筒车轴承水润滑流场仿真系统所需的桶和初始数据
"""
import os
import sys
from datetime import datetime, timedelta
import random
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from database.influxdb_client import InfluxDBClientWrapper


def init_database():
    print("=" * 60)
    print("  古代筒车轴承水润滑流场仿真系统 - InfluxDB 初始化")
    print("=" * 60)

    client = InfluxDBClientWrapper()

    print("\n[1/4] 检查连接状态...")
    if not client.test_connection():
        print("❌ InfluxDB 连接失败！请确保 InfluxDB 服务已启动。")
        return False
    print("✅ InfluxDB 连接成功")

    print("\n[2/4] 创建数据桶...")
    bucket_name = os.getenv('INFLUXDB_BUCKET', 'bearing_data')
    client.create_bucket(bucket_name)
    print(f"✅ 数据桶 '{bucket_name}' 已创建或已存在")

    print("\n[3/4] 检查组织...")
    org_name = os.getenv('INFLUXDB_ORG', 'water_lab')
    print(f"✅ 使用组织: {org_name}")

    print("\n[4/4] 写入初始模拟数据...")
    write_initial_data(client)

    print("\n" + "=" * 60)
    print("  InfluxDB 初始化完成！")
    print("=" * 60)
    return True


def write_initial_data(client: InfluxDBClientWrapper, hours: int = 24):
    """写入初始历史模拟数据"""
    print(f"  生成过去 {hours} 小时的模拟数据...")

    bearing_ids = ['bearing_001', 'bearing_002', 'bearing_003']
    now = datetime.utcnow()

    count = 0
    for hour in range(hours, 0, -1):
        timestamp = now - timedelta(hours=hour)

        for bearing_id in bearing_ids:
            rpm_base = 30 + (hash(bearing_id) % 20)
            rpm = rpm_base + 5 * math.sin(hour * 0.5) + random.uniform(-2, 2)

            pressure_base = 150000 + (hash(bearing_id) % 50000)
            pressure = pressure_base + 10000 * math.sin(hour * 0.3) + random.uniform(-5000, 5000)

            temp_base = 25 + (hash(bearing_id) % 5)
            water_temp = temp_base + 3 * math.sin(hour * 0.25) + random.uniform(-0.5, 0.5)

            friction_coeff = 0.012 + 0.003 * math.sin(hour * 0.4) + random.uniform(-0.001, 0.001)

            eccentricity = 0.3 + 0.1 * math.sin(hour * 0.35) + random.uniform(-0.02, 0.02)
            eccentricity = max(0.05, min(0.9, eccentricity))

            omega = rpm * 2 * math.pi / 60
            bearing_radius = 0.05
            radial_clearance = 2e-4
            viscosity = 1.002e-3 * math.exp(-0.025 * (water_temp - 20))

            sommerfeld = (viscosity * omega * bearing_radius / (radial_clearance ** 2)) * \
                         (bearing_radius / radial_clearance) * (0.4) ** 2

            friction_torque = friction_coeff * 500 * bearing_radius
            power_loss = friction_torque * omega

            points = [
                {
                    "measurement": "bearing_sensor",
                    "tags": {
                        "bearing_id": bearing_id,
                        "location": "song_dynasty_wheel",
                    },
                    "fields": {
                        "rpm": float(rpm),
                        "water_pressure": float(pressure),
                        "friction_coefficient": float(friction_coeff),
                        "water_temperature": float(water_temp),
                        "eccentricity_ratio": float(eccentricity),
                        "sommerfeld_number": float(sommerfeld),
                        "friction_torque": float(friction_torque),
                        "power_loss": float(power_loss),
                        "min_film_thickness": float(radial_clearance * (1 - eccentricity)),
                    },
                    "time": timestamp.isoformat() + "Z",
                }
            ]
            client.write_points(points)
            count += 1

    print(f"  ✅ 已写入 {count} 条历史数据点")


def main():
    try:
        success = init_database()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
