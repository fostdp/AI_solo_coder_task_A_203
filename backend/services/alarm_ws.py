"""告警与WebSocket服务：订阅friction_result与flow_result，生成告警并向WebSocket客户端广播。"""
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from ..config import get_bearing_config, get_messaging_config, get_nested
from ..messaging import MessageBus

log = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理，与原main.py保持API兼容。"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        with self._lock:
            self.active_connections[client_id] = websocket

    def disconnect(self, client_id: str):
        with self._lock:
            self.active_connections.pop(client_id, None)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        with self._lock:
            connections = list(self.active_connections.items())
        for cid, ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(cid)
        if dead:
            with self._lock:
                for cid in dead:
                    self.active_connections.pop(cid, None)

    @property
    def connection_count(self) -> int:
        return len(self.active_connections)


class AlarmWebSocketService:
    """
    订阅: bearing:friction_result, bearing:flow_result
    发布: bearing:alerts
    职责: 告警判定 + WebSocket广播 + 告警历史
    """

    def __init__(self, bus: Optional[MessageBus] = None,
                 manager: Optional[ConnectionManager] = None,
                 auto_subscribe: bool = True):
        self.bus = bus or MessageBus.instance()
        self.manager = manager or ConnectionManager()
        self.cfg = get_bearing_config()
        self.msg_cfg = get_messaging_config()

        alerts_cfg = get_nested(self.cfg, 'alerts', {})
        self.rupture_threshold = float(alerts_cfg.get('film_rupture_risk_threshold', 0.7))
        self.severe_cav = float(alerts_cfg.get('cavitation_severe_area_fraction', 0.2))
        self.history_max = int(alerts_cfg.get('history_max_length', 100))

        self.alert_history: List[Dict[str, Any]] = []
        self._history_lock = threading.Lock()
        self._last_flow: Dict[str, Dict[str, Any]] = {}

        if auto_subscribe:
            self.bus.subscribe('flow_result', self._on_flow)
            self.bus.subscribe('friction_result', self._on_friction)
            self.bus.subscribe('raw_data', self._on_raw)
            log.info('AlarmWebSocketService 已订阅 flow_result / friction_result / raw_data')

    # ---------- 告警判定 ----------
    def evaluate(self, bearing_id: str,
                 flow: Optional[Dict[str, Any]],
                 friction: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        now = datetime.utcnow().isoformat()

        if flow is not None:
            rupture_risk = float(flow.get('film_rupture_risk', 0.0))
            if rupture_risk >= self.rupture_threshold:
                alerts.append({
                    'bearing_id': bearing_id,
                    'type': 'film_rupture',
                    'severity': 'critical',
                    'message': f'水膜破裂风险 {rupture_risk*100:.1f}% 超过阈值 {self.rupture_threshold*100:.0f}%',
                    'value': rupture_risk,
                    'timestamp': now,
                })
            elif rupture_risk >= self.rupture_threshold * 0.7:
                alerts.append({
                    'bearing_id': bearing_id,
                    'type': 'film_warning',
                    'severity': 'warning',
                    'message': f'水膜变薄警告，破裂风险 {rupture_risk*100:.1f}%',
                    'value': rupture_risk,
                    'timestamp': now,
                })

            cav_area = float(flow.get('cavitation_area_fraction', 0.0))
            if cav_area >= self.severe_cav:
                alerts.append({
                    'bearing_id': bearing_id,
                    'type': 'cavitation_severe',
                    'severity': 'warning',
                    'message': f'严重空化，空化面积 {cav_area*100:.1f}%',
                    'value': cav_area,
                    'timestamp': now,
                })

        if friction is not None:
            status = friction.get('power_status', 'normal')
            severity = friction.get('power_severity', 'low')
            power = float(friction.get('power_loss_watts', 0.0))
            if status == 'overload':
                alerts.append({
                    'bearing_id': bearing_id,
                    'type': 'power_overload',
                    'severity': 'critical',
                    'message': f'摩擦功耗过载 {power*1000:.1f} mW，状态={status}',
                    'value': power,
                    'timestamp': now,
                })
            elif status == 'warning':
                alerts.append({
                    'bearing_id': bearing_id,
                    'type': 'power_warning',
                    'severity': 'warning',
                    'message': f'摩擦功耗偏高 {power*1000:.1f} mW，状态={status}',
                    'value': power,
                    'timestamp': now,
                })

            Trise = float(friction.get('temperature_rise_k', 0.0))
            if Trise >= get_nested(self.cfg, 'friction.temperature_rise_overload_k', 30.0):
                alerts.append({
                    'bearing_id': bearing_id,
                    'type': 'thermal_overload',
                    'severity': 'critical',
                    'message': f'温升过高 {Trise:.1f} K',
                    'value': Trise,
                    'timestamp': now,
                })
        return alerts

    # ---------- 发布 ----------
    def push_alerts(self, alerts: List[Dict[str, Any]]) -> None:
        if not alerts:
            return
        with self._history_lock:
            self.alert_history.extend(alerts)
            if len(self.alert_history) > self.history_max:
                self.alert_history = self.alert_history[-self.history_max:]
        for a in alerts:
            self.bus.publish('alerts', a)

    async def ws_broadcast(self, message: Dict[str, Any]) -> None:
        await self.manager.broadcast(message)

    # ---------- 订阅回调 ----------
    def _on_flow(self, flow: Dict[str, Any]) -> None:
        bid = flow.get('bearing_id')
        if not bid:
            return
        self._last_flow[bid] = flow

    def _on_friction(self, friction: Dict[str, Any]) -> None:
        bid = friction.get('bearing_id')
        if not bid:
            return
        flow = self._last_flow.get(bid)
        alerts = self.evaluate(bid, flow, friction)
        if alerts:
            self.push_alerts(alerts)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                for a in alerts:
                    if loop.is_running():
                        loop.create_task(self.ws_broadcast({'type': 'alert', 'data': a}))
                    else:
                        asyncio.run(self.ws_broadcast({'type': 'alert', 'data': a}))
            except Exception as e:
                log.error('WebSocket广播告警失败: %s', e)

    def _on_raw(self, raw: Dict[str, Any]) -> None:
        """接收raw_data时，如已有告警字段则直接推送。"""
        for key in ('film_status', 'power_status'):
            status = raw.get(key)
            if status and status != 'normal':
                bid = raw.get('bearing_id', 'unknown')
                self.push_alerts([{
                    'bearing_id': bid,
                    'type': key,
                    'severity': 'critical' if status in ('ruptured', 'overload') else 'warning',
                    'message': f'{key}={status}',
                    'value': status,
                    'timestamp': raw.get('received_at') or datetime.utcnow().isoformat(),
                }])

    # ---------- 查询 ----------
    def get_history(self, limit: int = 50, bearing_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._history_lock:
            hist = list(self.alert_history)
        if bearing_id:
            hist = [h for h in hist if h.get('bearing_id') == bearing_id]
        return hist[-limit:]


__all__ = ['AlarmWebSocketService', 'ConnectionManager']
