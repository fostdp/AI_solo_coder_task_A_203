"""配置加载器：从JSON配置文件读取流体/轴承/消息总线参数，并剥离C风格注释。"""
import json
import os
import re
import threading
from typing import Any, Dict, Optional


_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_C_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_LINE_COMMENT_RE = re.compile(r'(?<!:)//.*$', re.MULTILINE)

_cache: Dict[str, Any] = {}
_lock = threading.RLock()


def _strip_comments(raw: str) -> str:
    out = _C_COMMENT_RE.sub('', raw)
    out = _LINE_COMMENT_RE.sub('', out)
    return out


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    stripped = _strip_comments(raw)
    return json.loads(stripped)


def load_config(name: str, reload: bool = False) -> Dict[str, Any]:
    """加载命名配置。name ∈ {'fluid', 'bearing', 'messaging'}。"""
    with _lock:
        if reload or name not in _cache:
            path = os.path.join(_CONFIG_DIR, f'{name}_params.json') \
                if name != 'messaging' else os.path.join(_CONFIG_DIR, 'messaging.json')
            if not os.path.exists(path):
                raise FileNotFoundError(f'配置文件不存在: {path}')
            _cache[name] = _load_json(path)
        return _cache[name]


def get_fluid_config() -> Dict[str, Any]:
    cfg = load_config('fluid')
    if 'fluid' in cfg and isinstance(cfg['fluid'], dict):
        return cfg['fluid']
    return cfg


def get_bearing_config() -> Dict[str, Any]:
    cfg = load_config('bearing')
    if 'bearing' in cfg and isinstance(cfg['bearing'], dict) and 'solver' not in cfg['bearing']:
        return cfg
    return cfg


def get_messaging_config() -> Dict[str, Any]:
    return load_config('messaging')


def get_channel(name: str) -> str:
    msg = get_messaging_config()
    return msg['channels'][name]


def get_redis_config() -> Dict[str, Any]:
    return dict(get_messaging_config()['redis'])


def reload_all() -> None:
    with _lock:
        for k in list(_cache.keys()):
            load_config(k, reload=True)


def get_nested(d: Dict[str, Any], dotted: str, default: Optional[Any] = None) -> Any:
    cur = d
    for part in dotted.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur
