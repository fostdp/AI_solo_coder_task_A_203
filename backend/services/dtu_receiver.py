"""DTU接收器：负责传感器数据的接收、校验、存储并向消息总线发布原始数据。"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from ..config import get_messaging_config, get_nested
from ..database import InfluxDBClientWrapper
from ..messaging import MessageBus
from ..models.bearing import BearingData, BearingDataReceived

log = logging.getLogger(__name__)


class DTUReceiver:
    """
    数据流：
      HTTP/RPC原始数据 → Pydantic校验 → InfluxDB持久化 → Redis发布(raw_data/live_update)
    """

    def __init__(self, bus: Optional[MessageBus] = None,
                 db: Optional[InfluxDBClientWrapper] = None,
                 cache_ttl: Optional[int] = None):
        self.bus = bus or MessageBus.instance()
        self.db = db or InfluxDBClientWrapper()
        self.cache_ttl = cache_ttl or get_nested(
            get_messaging_config(), 'cache_ttl_seconds.bearing_latest', 3600)
        self._last_cache: Dict[str, Dict[str, Any]] = {}

    # ---------- 校验 ----------
    def validate(self, bearing_id: str, raw: Dict[str, Any]) -> Tuple[Optional[BearingData], Optional[str]]:
        try:
            data = BearingData(bearing_id=bearing_id, timestamp=raw.get('timestamp'), **raw)
            return data, None
        except ValidationError as e:
            errors = []
            for err in e.errors():
                loc = '.'.join(str(x) for x in err['loc'])
                errors.append(f'{loc}: {err["msg"]}')
            return None, '; '.join(errors)

    # ---------- 处理 ----------
    def receive(self, bearing_id: str, raw: Dict[str, Any]) -> BearingDataReceived:
        """接收传感器数据：校验→存储→发布。"""
        data, err = self.validate(bearing_id, raw)
        if err is not None:
            log.warning('轴承 %s 数据校验失败: %s', bearing_id, err)
            raise ValueError(f'数据校验失败: {err}')

        ts = data.timestamp or datetime.utcnow()
        record = data.model_dump()
        record['bearing_id'] = bearing_id
        record['received_at'] = ts.isoformat() if isinstance(ts, datetime) else str(ts)

        numeric_fields = {
            k: v for k, v in record.items()
            if isinstance(v, (int, float)) and k != 'timestamp'
        }
        tags = {
            'bearing_id': bearing_id,
            'location': record.get('location') or 'song_dynasty_wheel',
        }
        try:
            self.db.write_bearing_data(
                bearing_id=bearing_id,
                data=numeric_fields,
                timestamp=ts,
            )
        except Exception as e:
            log.error('写入InfluxDB失败 bearing=%s: %s', bearing_id, e)

        # 缓存
        self._last_cache[bearing_id] = record
        try:
            self.bus.setex(f'bearing:latest:{bearing_id}', self.cache_ttl, record)
        except Exception:
            pass

        # 发布原始数据
        self.bus.publish('raw_data', record)
        # 发布前端实时更新
        self.bus.publish('live_update', {
            'bearing_id': bearing_id,
            'timestamp': record.get('received_at'),
            'rpm': record.get('rpm'),
            'water_pressure': record.get('water_pressure'),
            'friction_coefficient': record.get('friction_coefficient'),
            'water_temperature': record.get('water_temperature'),
            'power_loss_watts': record.get('power_loss_watts'),
            'eccentricity_ratio': record.get('eccentricity_ratio'),
            'cavitation_area_fraction': record.get('cavitation_area_fraction'),
            'film_status': record.get('film_status'),
            'power_status': record.get('power_status'),
        })

        return BearingDataReceived(
            bearing_id=bearing_id,
            timestamp=ts,
            status='accepted',
            message='Data validated, stored and published',
        )

    # ---------- 查询 ----------
    def get_latest(self, bearing_id: str) -> Optional[Dict[str, Any]]:
        cached = self._last_cache.get(bearing_id)
        if cached:
            return cached
        v = self.bus.get(f'bearing:latest:{bearing_id}')
        if v:
            self._last_cache[bearing_id] = v
            return v
        return None

    def list_recent_ids(self) -> list:
        return list(self._last_cache.keys())


__all__ = ['DTUReceiver']
