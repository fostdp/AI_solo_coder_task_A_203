"""消息总线：基于Redis Pub/Sub的模块间通信层。Redis不可用时自动降级到fakeredis（内存实现）。"""
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from ..config import get_channel, get_redis_config

log = logging.getLogger(__name__)


def _try_create_redis(cfg: Dict[str, Any]):
    fake = cfg.pop('use_fake_if_unavailable', True)
    prefer_fake = cfg.pop('prefer_fake', False)
    if prefer_fake:
        try:
            import fakeredis
            return fakeredis.FakeRedis(decode_responses=cfg.get('decode_responses', True)), 'fakeredis-preferred'
        except Exception as e:
            log.error('prefer_fake 但 fakeredis 不可用: %s', e)
    try:
        import redis as redis_lib
        r = redis_lib.Redis(**cfg)
        r.ping()
        return r, 'real-redis'
    except Exception as e:
        log.warning('真实Redis不可用: %s', e)
        if not fake:
            raise
    try:
        import fakeredis
        return fakeredis.FakeRedis(decode_responses=cfg.get('decode_responses', True)), 'fakeredis'
    except Exception as e:
        log.error('fakeredis 也不可用: %s', e)
        raise


class MessageBus:
    """发布/订阅总线，支持publish、subscribe、request-reply。"""

    _instance: Optional['MessageBus'] = None
    _lock = threading.Lock()

    def __init__(self, redis_cfg: Optional[Dict[str, Any]] = None):
        cfg = redis_cfg or get_redis_config()
        self._redis, self._mode = _try_create_redis(dict(cfg))
        self._subscribers: Dict[str, List[Callable]] = {}
        self._sub_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reply_callbacks: Dict[str, Callable] = {}
        log.info('MessageBus 初始化完成，模式=%s', self._mode)

    @classmethod
    def instance(cls) -> 'MessageBus':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = MessageBus()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            old = cls._instance
            cls._instance = None
        if old is not None:
            try:
                old._stop.set()
            except Exception:
                pass

    @property
    def mode(self) -> str:
        return self._mode

    # ---------- 发布 ----------
    def publish(self, channel_name: str, payload: Dict[str, Any]) -> int:
        ch = get_channel(channel_name)
        msg = json.dumps(payload, ensure_ascii=False, default=str)
        try:
            return self._redis.publish(ch, msg)
        except Exception as e:
            log.error('发布失败 channel=%s: %s', ch, e)
            return 0

    # ---------- 订阅 ----------
    def subscribe(self, channel_name: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        ch = get_channel(channel_name)
        with self._lock:
            self._subscribers.setdefault(ch, []).append(callback)
            if self._sub_thread is None:
                self._start_subscriber_loop()

    def _start_subscriber_loop(self) -> None:
        self._sub_thread = threading.Thread(
            target=self._sub_loop, name='msgbus-sub', daemon=True,
        )
        self._sub_thread.start()

    def _sub_loop(self) -> None:
        ps = self._redis.pubsub(ignore_subscribe_messages=True)
        try:
            ps.subscribe(**{ch: lambda m, c=ch: self._dispatch(c, m)
                            for ch in self._subscribers})
        except Exception:
            channels = list(self._subscribers.keys())
            ps.subscribe(*channels)
        while not self._stop.is_set():
            try:
                msg = ps.get_message(timeout=0.5)
                if msg and msg.get('type') == 'message':
                    self._dispatch(msg['channel'], msg)
            except Exception as e:
                log.debug('sub loop 异常: %s', e)
                time.sleep(0.1)

    def _dispatch(self, channel: str, raw: Any) -> None:
        try:
            data = raw.get('data') if isinstance(raw, dict) else raw
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            payload = json.loads(data)
        except Exception as e:
            log.error('消息解析失败: %s', e)
            return
        for cb in list(self._subscribers.get(channel, [])):
            try:
                cb(payload)
            except Exception as e:
                log.exception('订阅回调异常 channel=%s: %s', channel, e)
        if payload.get('__reply_to__') and payload.get('__request_id__'):
            rid = payload['__request_id__']
            cb = self._reply_callbacks.pop(rid, None)
            if cb:
                try:
                    cb(payload)
                except Exception as e:
                    log.exception('request-reply回调异常: %s', e)

    # ---------- Request-Reply ----------
    def request(self, request_channel: str, payload: Dict[str, Any],
                timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """发送请求并等待应答（一次性）。"""
        reply_ch = get_channel(request_channel) + ':reply'
        rid = str(uuid.uuid4())
        ev = threading.Event()
        result: Dict[str, Any] = {}

        def on_reply(msg):
            result.update(msg)
            ev.set()

        self._reply_callbacks[rid] = on_reply
        self.subscribe(request_channel + ':reply', on_reply)

        envelope = dict(payload)
        envelope['__request_id__'] = rid
        envelope['__reply_to__'] = reply_ch
        self.publish(request_channel, envelope)

        ev.wait(timeout=timeout)
        self._reply_callbacks.pop(rid, None)
        return result or None

    def reply(self, original: Dict[str, Any], payload: Dict[str, Any]) -> None:
        ch = original.get('__reply_to__')
        if not ch:
            return
        reply_payload = dict(payload)
        reply_payload['__request_id__'] = original.get('__request_id__')
        try:
            self._redis.publish(ch, json.dumps(reply_payload, ensure_ascii=False, default=str))
        except Exception as e:
            log.error('应答失败: %s', e)

    # ---------- 缓存辅助 ----------
    def setex(self, key: str, seconds: int, value: Any) -> None:
        try:
            self._redis.setex(key, seconds, json.dumps(value, ensure_ascii=False, default=str))
        except Exception as e:
            log.warning('setex失败: %s', e)

    def get(self, key: str) -> Optional[Any]:
        try:
            v = self._redis.get(key)
            if v is None:
                return None
            if isinstance(v, bytes):
                v = v.decode('utf-8')
            return json.loads(v)
        except Exception:
            return None

    def close(self) -> None:
        self._stop.set()
        try:
            self._redis.close()
        except Exception:
            pass


__all__ = ['MessageBus']
