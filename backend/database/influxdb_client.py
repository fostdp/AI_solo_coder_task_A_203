import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta

try:
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS
    HAS_INFLUXDB = True
except ImportError:
    HAS_INFLUXDB = False


class InfluxDBClientWrapper:
    def __init__(self):
        self.url = os.getenv('INFLUXDB_URL', 'http://localhost:8086')
        self.token = os.getenv('INFLUXDB_TOKEN', 'my-secret-token')
        self.org = os.getenv('INFLUXDB_ORG', 'water_lab')
        self.bucket = os.getenv('INFLUXDB_BUCKET', 'bearing_data')

        self.client = None
        self.write_api = None
        self.query_api = None
        self.delete_api = None

        if HAS_INFLUXDB:
            self._connect()

    def _connect(self):
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org,
            )
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.query_api = self.client.query_api()
            self.delete_api = self.client.delete_api()
        except Exception as e:
            print(f"Warning: Failed to connect to InfluxDB: {e}")

    def test_connection(self) -> bool:
        if not HAS_INFLUXDB or not self.client:
            return False
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def create_bucket(self, bucket_name: Optional[str] = None):
        if not HAS_INFLUXDB or not self.client:
            return
        bucket_name = bucket_name or self.bucket
        try:
            buckets_api = self.client.buckets_api()
            existing = buckets_api.find_bucket_by_name(bucket_name)
            if not existing:
                org_id = self._get_org_id()
                buckets_api.create_bucket(
                    bucket_name=bucket_name,
                    org_id=org_id,
                )
        except Exception as e:
            print(f"Warning: Could not create bucket: {e}")

    def _get_org_id(self) -> Optional[str]:
        if not HAS_INFLUXDB or not self.client:
            return None
        try:
            orgs_api = self.client.organizations_api()
            orgs = orgs_api.find_organizations(org=self.org)
            if orgs:
                return orgs[0].id
        except Exception:
            pass
        return None

    def write_points(self, points: List[Dict]):
        if not HAS_INFLUXDB or not self.write_api:
            return
        try:
            influx_points = []
            for p in points:
                point = Point(p["measurement"])
                for tag_key, tag_val in p.get("tags", {}).items():
                    point.tag(tag_key, tag_val)
                for field_key, field_val in p.get("fields", {}).items():
                    point.field(field_key, field_val)
                if "time" in p:
                    point.time(p["time"])
                influx_points.append(point)

            self.write_api.write(
                bucket=self.bucket,
                org=self.org,
                record=influx_points,
            )
        except Exception as e:
            print(f"Warning: Failed to write points: {e}")

    def write_bearing_data(self, bearing_id: str, data: Dict[str, float],
                           timestamp: Optional[datetime] = None):
        point = {
            "measurement": "bearing_sensor",
            "tags": {
                "bearing_id": bearing_id,
                "location": "song_dynasty_wheel",
            },
            "fields": data,
        }
        if timestamp:
            point["time"] = timestamp.isoformat() + "Z"
        self.write_points([point])

    def query_bearing_data(
        self,
        bearing_id: str,
        start_time: str = "-1h",
        end_time: str = "now()",
        fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        if not HAS_INFLUXDB or not self.query_api:
            return []

        field_filter = ""
        if fields:
            field_conditions = " or ".join(
                [f'r["_field"] == "{f}"' for f in fields]
            )
            field_filter = f'|> filter(fn: (r) => {field_conditions})'

        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: {start_time}, stop: {end_time})
            |> filter(fn: (r) => r["_measurement"] == "bearing_sensor")
            |> filter(fn: (r) => r["bearing_id"] == "{bearing_id}")
            {field_filter}
            |> sort(columns: ["_time"])
        '''

        try:
            result = self.query_api.query(query=query, org=self.org)
            records = []
            for table in result:
                for record in table.records:
                    records.append({
                        "time": record.get_time(),
                        "field": record.get_field(),
                        "value": record.get_value(),
                        "bearing_id": record.values.get("bearing_id"),
                    })
            return records
        except Exception as e:
            print(f"Warning: Query failed: {e}")
            return []

    def get_latest_data(self, bearing_id: str) -> Optional[Dict[str, Any]]:
        if not HAS_INFLUXDB or not self.query_api:
            return None

        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: -1h)
            |> filter(fn: (r) => r["_measurement"] == "bearing_sensor")
            |> filter(fn: (r) => r["bearing_id"] == "{bearing_id}")
            |> last()
        '''

        try:
            result = self.query_api.query(query=query, org=self.org)
            data = {}
            for table in result:
                for record in table.records:
                    data[record.get_field()] = record.get_value()
                    if "time" not in data:
                        data["time"] = record.get_time()
            return data if data else None
        except Exception as e:
            print(f"Warning: Query failed: {e}")
            return None

    def get_aggregated_data(
        self,
        bearing_id: str,
        window: str = "5m",
        start_time: str = "-24h",
    ) -> List[Dict]:
        if not HAS_INFLUXDB or not self.query_api:
            return []

        query = f'''
        from(bucket: "{self.bucket}")
            |> range(start: {start_time})
            |> filter(fn: (r) => r["_measurement"] == "bearing_sensor")
            |> filter(fn: (r) => r["bearing_id"] == "{bearing_id}")
            |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
            |> yield(name: "mean")
        '''

        try:
            result = self.query_api.query(query=query, org=self.org)
            records = []
            for table in result:
                for record in table.records:
                    records.append({
                        "time": record.get_time(),
                        "field": record.get_field(),
                        "value": record.get_value(),
                    })
            return records
        except Exception as e:
            print(f"Warning: Query failed: {e}")
            return []

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
            self.write_api = None
            self.query_api = None
