"""evals.metrics.slots_from_tool_calls 的离线确定性单测。

把端到端采集到的有序工具调用序列 ``[{name, args}]`` 还原成扁平槽位 dict，
喂 ``slot_completeness`` 指标。纯数据断言，不触网、不跑 LLM。

覆盖（见 change evals-wire-slot-completeness 的 spec/design）：
- 跨工具合并（find_technician + create_appointment）
- 同名冲突 last-write-wins（按 tool_calls 顺序，后者覆盖）
- 哨兵默认值（未知/无）不计入
- 空/None 工具调用返回 None（让该用例标 N/A，不伪造空 dict）
- technician_name 归一为槽位键 technician
"""

from domains import load_domain
from evals.metrics import slots_from_tool_calls

# 槽位键映射随域声明（change oncall-evals-bootstrap）；这里取预约域的那份，
# 断言内容与重构前一字不差——它是那次去域耦合的等价性锚点之一。
_SLOT_MAP = load_domain("appointment").eval_profile.slot_key_map


def test_merges_slots_across_tools():
    # find_technician 抽到 project/gender，create_appointment 抽到 start_time/duration/project。
    tool_calls = [
        {"name": "find_technician", "args": {"project": "推拿", "gender": "male"}},
        {
            "name": "create_appointment",
            "args": {"start_time": "2026-06-26 14:00", "duration": "60分钟", "project": "推拿"},
        },
    ]
    assert slots_from_tool_calls(tool_calls, _SLOT_MAP) == {
        "project": "推拿",
        "gender": "male",
        "start_time": "2026-06-26 14:00",
        "duration": "60分钟",
    }


def test_same_slot_conflict_last_write_wins():
    # 同一槽位 project 在两个工具调用中取值不同 → 取后出现的（确定性 last-write-wins）。
    tool_calls = [
        {"name": "find_technician", "args": {"project": "按摩"}},
        {"name": "create_appointment", "args": {"project": "推拿"}},
    ]
    assert slots_from_tool_calls(tool_calls, _SLOT_MAP)["project"] == "推拿"


def test_sentinel_defaults_not_counted():
    # 工具 schema 的可选槽位默认占位串（未知/无）视为「未抽取」，不写入。
    tool_calls = [
        {
            "name": "find_technician",
            "args": {"project": "推拿", "gender": "未知", "preference": "无"},
        }
    ]
    slots = slots_from_tool_calls(tool_calls, _SLOT_MAP)
    assert slots == {"project": "推拿"}
    assert "gender" not in slots
    assert "preference" not in slots


def test_sentinel_does_not_overwrite_real_value():
    # 先有真值、后出现哨兵默认值 → 哨兵被跳过，真值保留（不被默认值覆盖）。
    tool_calls = [
        {"name": "find_technician", "args": {"project": "推拿"}},
        {"name": "create_appointment", "args": {"project": "未知"}},
    ]
    assert slots_from_tool_calls(tool_calls, _SLOT_MAP)["project"] == "推拿"


def test_technician_name_normalized_to_technician():
    # 工具 schema 字段名 technician_name 归一为槽位键 technician。
    tool_calls = [{"name": "find_technician", "args": {"technician_name": "李师傅"}}]
    slots = slots_from_tool_calls(tool_calls, _SLOT_MAP)
    assert slots == {"technician": "李师傅"}
    assert "technician_name" not in slots


def test_non_slot_args_ignored():
    # technician_id / session_id 不是抽取槽位（ID/会话基建），不纳入。
    tool_calls = [
        {
            "name": "create_appointment",
            "args": {"technician_id": 7, "session_id": "abc", "project": "推拿"},
        }
    ]
    assert slots_from_tool_calls(tool_calls, _SLOT_MAP) == {"project": "推拿"}


def test_empty_or_none_returns_none():
    # 无工具调用（真跑失败/未跑 loop）→ None，让该用例槽位指标标 N/A，不伪造分母。
    assert slots_from_tool_calls(None, _SLOT_MAP) is None
    assert slots_from_tool_calls([], _SLOT_MAP) is None


def test_tools_ran_but_no_slots_returns_empty_dict():
    # 有工具调用但无任何槽位字段（如只 search_knowledge）→ 返回 {}（非 None）：
    # 表示「跑了但没抽到槽位」，得 0 分而非 N/A（与 None 语义区分）。
    tool_calls = [{"name": "search_knowledge", "args": {"query": "营业时间"}}]
    assert slots_from_tool_calls(tool_calls, _SLOT_MAP) == {}
