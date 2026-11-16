"""合规撤回的隐私原语。

只产出不可逆指纹与脱敏标识，任何函数都不得保留或回吐请求原文、可读请求标识。
- 指纹用于跨导入/撤回/封账的稳定关联，键空间按服务隔离，同名请求在不同服务互不可见。
- 盐值由设置注入，使指纹不可被离线字典反推。
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any


def request_fingerprint(service: str, request_id: str, salt: str) -> str:
    """生成 (service, request_id) 绑定的不可逆 HMAC-SHA256 指纹。"""
    msg = f"{service}\x1f{request_id}".encode("utf-8")
    return hmac.new(str(salt).encode("utf-8"), msg, hashlib.sha256).hexdigest()


def masked_hint(service: str, request_id: str) -> str:
    """仅用于人工核对的脱敏标识，不含完整可读 ID（不掺盐，可稳定展示但不可逆推全文）。"""
    digest = hashlib.sha256(f"{service}\x1f{request_id}".encode("utf-8")).hexdigest()
    return f"{service}:{digest[:8]}"


def service_digest(service: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}\x1f{service}".encode("utf-8")).hexdigest()[:12]


def anonymous_summary(active_count: int, error_count: int) -> dict:
    """匿名汇总：只给计数与差错率，不给任何可定位到单请求的信息。"""
    rate = round(error_count / active_count, 6) if active_count else 0.0
    return {
        "active_count": active_count,
        "error_count": error_count,
        "error_rate": rate,
    }


def canonical_digest(value: Any) -> str:
    import json

    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
