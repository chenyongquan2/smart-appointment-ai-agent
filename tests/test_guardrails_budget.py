"""token 预算估算与打转检测单测（Phase 5）。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from harness.guardrails.budget import SpinDetector, estimate_tokens


def _call(name: str, args: dict) -> dict:
    return {"name": name, "args": args, "id": "x", "type": "tool_call"}


# --------------------------------------------------------------------------- #
# estimate_tokens：字符数 / 4 的粗略近似
# --------------------------------------------------------------------------- #
def test_estimate_tokens_counts_content_chars():
    msgs = [HumanMessage(content="a" * 40), AIMessage(content="b" * 40)]
    # 80 字符 // 4 = 20
    assert estimate_tokens(msgs) == 20


def test_estimate_tokens_handles_content_blocks():
    msg = AIMessage(content=[{"type": "text", "text": "x" * 16}, "y" * 8])
    # 24 字符 // 4 = 6
    assert estimate_tokens([msg]) == 6


def test_estimate_tokens_empty():
    assert estimate_tokens([]) == 0


# --------------------------------------------------------------------------- #
# SpinDetector：连续相同 (name, args) 达到 repeat_limit 即判打转
# --------------------------------------------------------------------------- #
def test_spin_detected_on_consecutive_identical_calls():
    det = SpinDetector(repeat_limit=3)
    same = [_call("find_technician", {"project": "推拿"})]
    assert det.check(same) is False  # 1
    assert det.check(same) is False  # 2
    assert det.check(same) is True   # 3 → 打转


def test_spin_resets_when_args_differ():
    det = SpinDetector(repeat_limit=3)
    assert det.check([_call("find_technician", {"project": "推拿"})]) is False
    assert det.check([_call("find_technician", {"project": "按摩"})]) is False  # 参数不同，重置
    assert det.check([_call("find_technician", {"project": "按摩"})]) is False  # count=2
    assert det.check([_call("find_technician", {"project": "按摩"})]) is True   # count=3


def test_spin_args_key_order_insensitive():
    det = SpinDetector(repeat_limit=2)
    assert det.check([_call("t", {"a": 1, "b": 2})]) is False
    # 同一调用、键顺序不同应视为相同签名
    assert det.check([_call("t", {"b": 2, "a": 1})]) is True


def test_spin_disabled_when_limit_none():
    det = SpinDetector(repeat_limit=None)
    same = [_call("t", {})]
    for _ in range(10):
        assert det.check(same) is False
