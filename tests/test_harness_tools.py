"""harness.tools 各工具单测（Phase 2）。

策略:在工具 handler 延迟 import 的 service 模块命名空间上 monkeypatch service 类,
断言"合法参数正确转交 service"与"非法参数触发 Pydantic 校验且 service 不被调用"。
不依赖真实 DB / 网络。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from harness.tools.appointment import create_appointment
from harness.tools.availability import check_availability
from harness.tools.knowledge import search_knowledge
from harness.tools.preference import get_user_preferences
from harness.tools.technician import find_technician


# --- search_knowledge -------------------------------------------------------

async def test_search_knowledge_delegates(monkeypatch):
    calls: dict[str, Any] = {}

    class FakeKnowledgeService:
        initialized = True

        async def initialize(self):  # pragma: no cover - 不应被调用
            calls["initialized"] = True

        async def search(self, query, top_k=3, category=None):
            calls["search"] = (query, top_k, category)
            return [{"content": "doc", "score": 0.9}]

    import services.knowledge_service as ks
    monkeypatch.setattr(ks, "KnowledgeService", FakeKnowledgeService)

    result = await search_knowledge.run({"query": "营业时间", "top_k": 2})

    assert calls["search"] == ("营业时间", 2, None)
    assert result == [{"content": "doc", "score": 0.9}]


async def test_search_knowledge_invalid_args_skips_service(monkeypatch):
    called = {"hit": False}

    class FakeKnowledgeService:
        initialized = True

        async def search(self, *a, **k):  # pragma: no cover
            called["hit"] = True
            return []

    import services.knowledge_service as ks
    monkeypatch.setattr(ks, "KnowledgeService", FakeKnowledgeService)

    with pytest.raises(ValidationError):
        await search_knowledge.run({})  # 缺 query

    with pytest.raises(ValidationError):
        await search_knowledge.run({"query": "x", "top_k": 0})  # ge=1

    assert called["hit"] is False


# --- find_technician --------------------------------------------------------

async def test_find_technician_delegates(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeFinder:
        def find_technician_with_thought(self, history, yield_func=None):
            captured["history"] = history
            captured["yield_func"] = yield_func
            return {"id": 7, "name": "张伟"}

    import agents.appointment.technician_finder as tf
    monkeypatch.setattr(tf, "TechnicianFinder", FakeFinder)

    result = await find_technician.run(
        {
            "start_time": "2026-06-08 15:00",
            "duration": "60分钟",
            "project": "按摩",
            "gender": "男",
        }
    )

    assert result == {"id": 7, "name": "张伟"}
    assert captured["history"]["start_time"] == "2026-06-08 15:00"
    assert captured["yield_func"] is None


async def test_find_technician_invalid_args(monkeypatch):
    with pytest.raises(ValidationError):
        await find_technician.run({"duration": "60分钟"})  # 缺 start_time


# --- check_availability -----------------------------------------------------

async def test_check_availability_delegates(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeAppointmentService:
        def is_technician_available(self, tech_id, start, end):
            captured["args"] = (tech_id, start, end)
            return True

    import services.appointment_service as aps
    monkeypatch.setattr(aps, "AppointmentService", FakeAppointmentService)

    result = await check_availability.run(
        {"technician_id": 3, "start_time": "2026-06-08 15:00", "duration": "60分钟"}
    )

    assert result == {"available": True, "technician_id": 3}
    tech_id, start, end = captured["args"]
    assert tech_id == 3
    assert isinstance(start, datetime) and isinstance(end, datetime)
    assert (end - start).total_seconds() == 60 * 60


async def test_check_availability_bad_time_skips_service(monkeypatch):
    called = {"hit": False}

    class FakeAppointmentService:
        def is_technician_available(self, *a, **k):  # pragma: no cover
            called["hit"] = True
            return True

    import services.appointment_service as aps
    monkeypatch.setattr(aps, "AppointmentService", FakeAppointmentService)

    result = await check_availability.run(
        {"technician_id": 3, "start_time": "未知", "duration": "60分钟"}
    )
    assert result["available"] is False
    assert "error" in result
    assert called["hit"] is False


# --- create_appointment -----------------------------------------------------

async def test_create_appointment_delegates(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeAppointmentService:
        def save_appointment(self, technician_id, start_time, end_time,
                             appointment_history, session_id):
            captured["call"] = dict(
                technician_id=technician_id,
                start_time=start_time,
                end_time=end_time,
                session_id=session_id,
            )
            return True

    import services.appointment_service as aps
    monkeypatch.setattr(aps, "AppointmentService", FakeAppointmentService)

    result = await create_appointment.run(
        {
            "technician_id": 5,
            "start_time": "2026-06-08 10:00",
            "duration": "90分钟",
            "session_id": "sess-1",
            "project": "推拿",
        }
    )

    assert result["success"] is True
    assert captured["call"]["technician_id"] == "5"  # service 期望 str
    assert captured["call"]["session_id"] == "sess-1"
    assert isinstance(captured["call"]["start_time"], datetime)


async def test_create_appointment_invalid_args():
    with pytest.raises(ValidationError):
        await create_appointment.run(
            {"technician_id": 5, "start_time": "2026-06-08 10:00", "duration": "90分钟"}
        )  # 缺 session_id


# --- get_user_preferences ---------------------------------------------------

async def test_get_user_preferences_delegates(monkeypatch):
    class FakeUserBehaviorService:
        def get_user_preferences(self, user_id):
            return [{"preference_type": "technician", "value": "张伟"}]

        def analyze_user_patterns(self, user_id):  # pragma: no cover
            return {"pattern": "active_user"}

    import services.user_behavior_service as ubs
    monkeypatch.setattr(ubs, "UserBehaviorService", FakeUserBehaviorService)

    result = await get_user_preferences.run({"user_id": "u1"})
    assert result["user_id"] == "u1"
    assert result["preferences"][0]["value"] == "张伟"
    assert "patterns" not in result


async def test_get_user_preferences_with_patterns(monkeypatch):
    class FakeUserBehaviorService:
        def get_user_preferences(self, user_id):
            return []

        def analyze_user_patterns(self, user_id):
            return {"pattern": "active_user"}

    import services.user_behavior_service as ubs
    monkeypatch.setattr(ubs, "UserBehaviorService", FakeUserBehaviorService)

    result = await get_user_preferences.run({"user_id": "u1", "include_patterns": True})
    assert result["patterns"] == {"pattern": "active_user"}
