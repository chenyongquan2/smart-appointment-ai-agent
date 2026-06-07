"""工具层共用的时间解析 helper。

沿用 Phase 1 ``AppointmentSlots`` 的时间约定（``YYYY-MM-DD HH:MM`` 字符串）与既有
``config.time_config`` / ``TechnicianFinder`` 的解析口径，避免在工具层重复造轮子。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from config.time_config import time_config


def parse_start_time(start_time_str: str) -> datetime | None:
    """把 ``YYYY-MM-DD HH:MM`` 字符串解析为 datetime；非法或"未知"返回 None。"""
    if not start_time_str or start_time_str == "未知":
        return None
    return time_config.parse_datetime(start_time_str)


def parse_duration_minutes(duration_str: str) -> int | None:
    """从时长字符串（如 ``180分钟``）提取分钟数；非法或"未知"返回 None。"""
    if not duration_str or duration_str == "未知":
        return None
    digits = "".join(filter(str.isdigit, str(duration_str)))
    if not digits:
        return None
    minutes = int(digits)
    return minutes if minutes > 0 else None


def resolve_time_window(start_time_str: str, duration_str: str) -> tuple[datetime, datetime] | None:
    """由起始时间字符串 + 时长字符串推导 ``(start, end)`` 时间窗；任一非法返回 None。"""
    start = parse_start_time(start_time_str)
    minutes = parse_duration_minutes(duration_str)
    if start is None or minutes is None:
        return None
    return start, start + timedelta(minutes=minutes)
