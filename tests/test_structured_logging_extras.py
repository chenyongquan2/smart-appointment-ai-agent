"""结构化日志必须输出 ``extra`` 业务字段（change: feishu-channel-integration）。

实测发现的缺口：`JsonFormatter` 原先只取固定四项（timestamp/level/logger/message），
把 ``extra={...}`` 全部丢弃。于是全应用写的结构化字段等于白写——日志看着"结构化"，
真要查「哪个 session、哪个 event_id、投递失败的原因」时一个字段都没有。

这批用例守住三件事：业务字段被输出、核心字段名不被顶掉、不可序列化的值不会让日志抛异常。
"""

from __future__ import annotations

import json
import logging

import pytest

from config.logging_setup import JsonFormatter


def render(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def make_record(msg: str = "已提交任务", **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="channels.lark.gateway", level=logging.INFO, pathname=__file__,
        lineno=1, msg=msg, args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# --------------------------------------------------------------------------- #
# 核心字段仍在（不破坏 structured-logging 既有需求）
# --------------------------------------------------------------------------- #
def test_core_fields_are_present():
    payload = render(make_record())

    assert set(payload) >= {"timestamp", "level", "logger", "message"}
    assert payload["level"] == "INFO"
    assert payload["logger"] == "channels.lark.gateway"
    assert payload["message"] == "已提交任务"


# --------------------------------------------------------------------------- #
# extra 业务字段被输出
# --------------------------------------------------------------------------- #
def test_extra_fields_are_emitted():
    payload = render(make_record(
        session_id="feishu:om_a", event_id="evt-1", scope="reply",
        root_id=None, message_id="om_b",
    ))

    assert payload["session_id"] == "feishu:om_a"
    assert payload["event_id"] == "evt-1"
    assert payload["scope"] == "reply"
    assert payload["message_id"] == "om_b"
    assert payload["root_id"] is None  # 显式的 null 也有信息量（说明该字段未下发）


def test_no_standard_record_noise_leaks():
    """不能把 LogRecord 的内部属性（pathname/lineno/threadName…）一并倒出来。"""
    payload = render(make_record(session_id="s"))

    for noisy in ("pathname", "lineno", "args", "msg", "levelno", "threadName"):
        assert noisy not in payload


# --------------------------------------------------------------------------- #
# 核心字段不被顶掉
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", ["timestamp", "level", "logger"])
def test_extra_cannot_override_core_fields(key):
    """logging 只保护 message/asctime，不保护我们自定的这三个——必须自己兜住。"""
    payload = render(make_record(**{key: "冒充值"}))

    assert payload[key] != "冒充值"


# --------------------------------------------------------------------------- #
# 不可序列化的值不能把日志变成新的故障
# --------------------------------------------------------------------------- #
def test_unserializable_extra_does_not_raise():
    """gateway 会把 asyncio.Task 塞进 metadata，delivery 记日志时可能带上枚举等对象。

    日志绝不能因为一个字段序列化不了就抛异常——那会把「记录一次失败」变成
    「再制造一次失败」，而且往往就发生在排障最需要日志的时候。
    """
    class Unserializable:
        def __repr__(self) -> str:
            return "<不可序列化对象>"

    payload = render(make_record(weird=Unserializable(), status=logging.INFO))

    assert payload["weird"] == "<不可序列化对象>"


def test_exception_info_still_included():
    try:
        raise ValueError("炸了")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="x", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="失败", args=(), exc_info=sys.exc_info(),
        )

    payload = render(record)

    assert "exc_info" in payload and "ValueError" in payload["exc_info"]


def test_output_is_single_line():
    """单行 JSON 是采集侧的硬要求——多行会被日志系统切成互不相干的条目。"""
    line = JsonFormatter().format(make_record(note="含\n换行的值"))

    assert "\n" not in line
    assert json.loads(line)["note"] == "含\n换行的值"
