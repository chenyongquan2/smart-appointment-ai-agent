"""「同一工具换参重复调用」信号的离线确定性单测（change: detect-repeated-tool-identity）。

## 这组测试守的是什么

`SpinDetector` 把参数计入签名，故「同一工具、参数每次不同」的打转护栏看不见——真实数据
实测**抓到病态 0/3**。本 change 加的是**观测信号**（不改护栏、不终止循环）。

下面的 span 全部**复现盘上 7 条真实 trace 的形状**（几步、每步几个调用、哪些参数在变），
但标识值是**合成的**：真实 trace 含真实 requestId 与同事原话，trace 目录 gitignore、而测试
进版本库——与「回灌 cases.jsonl 不得带 user_id」同一个道理。

## 为什么规则是「同身份跨步出现」而不是「连续签名相同」

在这 7 条形状上实测过 5 条候选规则：

    现状（连续整步签名全同×3）  抓到病态 0/3  误报 0
    B  同名连续×3（不看参数）    3/3         误报 3  ← 正当枚举全打死
    B' 同名连续×4              2/3         误报 2
    C  去掉宽度参数后连续×3      1/3         误报 0  ← 最直觉的修法
    D  同(工具,身份)出现≥3步     2/3         误报 0  ← 本实现

C 只有 1/3 是因为真实 step **一步里常含多个工具调用**（见
`test_pathological_window_widening` 的 step2），"连续整步签名相同"一遇多调用就散。
**问题在判据形状，不在签名算法。**
"""

from __future__ import annotations

from harness.observability.span import Span, SpanEvent
from harness.observability.trace_signals import (
    DEFAULT_REPEAT_IDENTITY_STEPS,
    detect_bad_signals,
    is_bad_trace,
)
from harness.tools.base import Tool
from pydantic import BaseModel

SIGNAL = "repeated_tool_identity"

# 合成的检索键：形状照搬真实 trace（一个不透明的长 id），值是假的。
FAKE_ID = "deadbeefdeadbeefdeadbeefdeadbeef"

# 与 domains/oncall/tools/vlog.py 的声明一致——测试里显式写出，便于看清「哪些算宽度」。
VLOG_BREADTH = frozenset({"window", "limit"})
KB_BREADTH = frozenset({"top_k"})


def _identity(args: dict, breadth: frozenset[str]) -> dict:
    return {k: v for k, v in args.items() if k not in breadth}


def _call(name: str, args: dict, breadth: frozenset[str]) -> SpanEvent:
    """构造一个带 identity 的 tool_call 事件（identity 由 AgentLoop 在记录时算，此处模拟）。"""
    return SpanEvent("tool_call", {"name": name, "args": args, "identity": _identity(args, breadth)})


def _step(i: int, events: list[SpanEvent]) -> Span:
    return Span(trace_id="t", span_id=f"s{i}", parent_id="t-root", name="step",
                start=float(i), end=float(i), events=events)


def _reply_step(i: int) -> Span:
    """终态回复那一步：无 tool_call（否则会顺带命中 max_steps_reached）。"""
    return _step(i, [SpanEvent("thought", {"text": "已给出结论"})])


def _root() -> Span:
    return Span(trace_id="t", span_id="t-root", parent_id=None, name="agent_loop.run",
                start=0.0, end=0.0, attributes={"user_input": "合成输入"})


# ══════════════════════════════════════════════════════════════════════════
# 病态形状 → MUST 命中
# ══════════════════════════════════════════════════════════════════════════
def test_pathological_window_widening():
    """★ 真实群聊那次坏 case 的形状：检索键固定，时间窗 2d→30m→7d 振荡，连吃三次超时。

    注意 step2 **一步内有两个调用**（prod/30m 与 uat/2d）——正是这个细节让「连续整步
    签名相同」那类规则失效（无论签名含不含宽度参数）。
    """
    spans = [
        _root(),
        _step(1, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "2d", "limit": 50}, VLOG_BREADTH)]),
        _step(2, [
            _call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "30m", "limit": 50}, VLOG_BREADTH),
            _call("vlog_query", {"term": [FAKE_ID], "env": "uat", "window": "2d", "limit": 50}, VLOG_BREADTH),
        ]),
        _step(3, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "7d", "limit": 50}, VLOG_BREADTH)]),
        _reply_step(4),
    ]
    signals = detect_bad_signals(spans)
    assert SIGNAL in signals, "真实坏 case 的形状必须命中——修前这里是空清单"
    assert is_bad_trace(spans) is True


def test_pathological_window_oscillating():
    """病态②：检索键固定，时间窗 6h→30m→12h 振荡（另一条真实 trace 的形状）。"""
    spans = [_root()] + [
        _step(i, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": w, "limit": 50}, VLOG_BREADTH)])
        for i, w in enumerate(["6h", "30m", "12h", "6h"], start=1)
    ] + [_reply_step(5)]
    assert SIGNAL in detect_bad_signals(spans)


def test_non_consecutive_still_detected():
    """不连续也要命中：同身份出现在第 1、3、5 步，中间夹别的工具。

    真实的病态模式里 `load_reference` 会插在两次 `vlog_query` 之间——要求连续就漏。
    """
    q = lambda w: _call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": w, "limit": 50}, VLOG_BREADTH)
    ref = _call("load_reference", {"name": "ocs-service-profiles"}, frozenset())
    spans = [
        _root(), _step(1, [q("6h")]), _step(2, [ref]), _step(3, [q("2d")]),
        _step(4, [ref]), _step(5, [q("7d")]), _reply_step(6),
    ]
    assert SIGNAL in detect_bad_signals(spans)


# ══════════════════════════════════════════════════════════════════════════
# 正当形状 → MUST NOT 命中（本规则相对 B/B' 的全部价值）
# ══════════════════════════════════════════════════════════════════════════
def test_legitimate_per_tenant_enumeration_not_flagged():
    """★★ 最关键的一条：逐租户枚举 MUST NOT 命中。

    检索键与时间窗都固定、只有 env 逐个变（prod→uat→stg→dev）——这是排障时正当的
    「同一个 id 逐个环境查一遍」。规则 B/B'（只看工具名）在这条上误报，那会让整个信号
    退化成噪声源；这条一旦回归，本 change 就白做了。
    """
    spans = [_root()] + [
        _step(i, [_call("vlog_query", {"term": [FAKE_ID], "env": env, "window": "2d", "limit": 200}, VLOG_BREADTH)])
        for i, env in enumerate(["prod", "uat", "stg", "dev"], start=1)
    ] + [_reply_step(5)]
    assert detect_bad_signals(spans) == [], "逐租户枚举是正当模式，绝不能进候选"


def test_legitimate_strategy_change_not_flagged():
    """正当②：换检索策略——先正则式 logsql、后改精确词 term 并收窄窗。"""
    spans = [
        _root(),
        _step(1, [_call("vlog_query", {"logsql": f'_msg:~"{FAKE_ID}"', "env": "prod", "window": "7d", "limit": 10}, VLOG_BREADTH)]),
        _step(2, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "7d", "limit": 10}, VLOG_BREADTH)]),
        _step(3, [_call("vlog_query", {"term": [FAKE_ID, "error"], "env": "prod", "window": "3d", "limit": 10}, VLOG_BREADTH)]),
        _reply_step(4),
    ]
    assert detect_bad_signals(spans) == []


def test_legitimate_parallel_multi_intent_not_flagged():
    """正当③：同一步内针对不同检索词并行调同一工具——验证「按步骤去重计数」这条口径。

    若按调用次数计数，这里一步就能顶到阈值，正当模式直接变误报。
    """
    spans = [
        _root(),
        _step(1, [
            _call("search_knowledge", {"query": "营业时间", "top_k": 3}, KB_BREADTH),
            _call("search_knowledge", {"query": "联系电话", "top_k": 3}, KB_BREADTH),
            _call("search_knowledge", {"query": "价格", "top_k": 3}, KB_BREADTH),
        ]),
        _reply_step(2),
    ]
    assert detect_bad_signals(spans) == []


def test_query_reformulation_not_covered():
    """非目标如实钉住：**改写漂移抓不到**——同工具反复改写检索键、多步无进展。

    真实数据里 `search_knowledge` 连查 6 次那条就是这个形状。检索键本身在变 → 身份不同
    → 规则 D 判不出。这不是缺陷，是本 change 明确排除的范围（`max_steps` 是它的兜底）；
    写成测试是为了让「已覆盖打转」这种误读没法成立。
    """
    queries = ["力气大 男技师", "技师 介绍 男师傅", "技师 男 推荐",
               "技师信息 师傅介绍", "门店服务 按摩", "门店介绍 店铺信息"]
    spans = [_root()] + [
        _step(i, [_call("search_knowledge", {"query": q, "top_k": 10}, KB_BREADTH)])
        for i, q in enumerate(queries, start=1)
    ] + [_reply_step(7)]
    assert SIGNAL not in detect_bad_signals(spans)


# ══════════════════════════════════════════════════════════════════════════
# 阈值、兼容性、与护栏的边界
# ══════════════════════════════════════════════════════════════════════════
def test_below_threshold_not_flagged():
    """同身份只出现 2 步 → 不命中（缺省阈值 3）。"""
    spans = [
        _root(),
        _step(1, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "6h", "limit": 50}, VLOG_BREADTH)]),
        _step(2, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "2d", "limit": 50}, VLOG_BREADTH)]),
        _reply_step(3),
    ]
    assert SIGNAL not in detect_bad_signals(spans)


def test_threshold_is_configurable():
    """阈值可配：同一批 span 在阈值 2 下命中、阈值 4 下不命中。"""
    spans = [
        _root(),
        _step(1, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "6h", "limit": 50}, VLOG_BREADTH)]),
        _step(2, [_call("vlog_query", {"term": [FAKE_ID], "env": "prod", "window": "2d", "limit": 50}, VLOG_BREADTH)]),
        _reply_step(3),
    ]
    assert SIGNAL in detect_bad_signals(spans, repeat_identity_steps=2)
    assert SIGNAL not in detect_bad_signals(spans, repeat_identity_steps=4)
    assert DEFAULT_REPEAT_IDENTITY_STEPS == 3


def test_legacy_trace_without_identity_never_fires():
    """诚实边界：老 trace 的 tool_call payload 没有 identity 字段 → 本信号不会命中。

    刻意不为老文件加「按参数名硬编码回退推断」的分支——那等于把域知识泄漏以"兼容"的
    名义请回来。覆盖自本 change 之后落的新 trace 起生效。
    """
    def legacy(w):  # 旧格式：只有 name/args
        return SpanEvent("tool_call", {"name": "vlog_query",
                                       "args": {"term": [FAKE_ID], "env": "prod", "window": w}})
    spans = [_root()] + [_step(i, [legacy(w)]) for i, w in enumerate(["2d", "30m", "7d"], 1)] + [_reply_step(4)]
    assert SIGNAL not in detect_bad_signals(spans)


def test_signal_name_is_not_confusable_with_guardrail():
    """信号名 MUST NOT 用泛化的 spin 字样——`spin_detected` 是护栏产生的、会终止循环。

    混起来会让人误以为护栏已经拦住了，而本 change 明确不改护栏。
    """
    assert "spin" not in SIGNAL


def test_signals_module_has_no_hardcoded_arg_names():
    """★ 守「域内容不泄漏进域无关运行时」：判定模块里不得出现具体参数名字面量。

    身份参数由 `AgentLoop` 按 `Tool.breadth_args` 算好；判定侧若自行按名字剔，就等于把
    域知识嵌进 harness（与记忆层那三处已知泄漏同类）。用 AST 取字符串常量而非扫源码文本
    ——扫文本会被 docstring 里的举例误伤（tests/test_tool_outcome.py 踩过同一个坑）。
    """
    import ast
    import inspect

    import harness.observability.trace_signals as mod

    tree = ast.parse(inspect.getsource(mod))
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                first = node.body[0]
                docstring_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    literals = [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.lineno not in docstring_lines
    ]
    for forbidden in ("window", "limit", "top_k", "term", "env"):
        assert forbidden not in literals, (
            f"trace_signals 出现了具体参数名 {forbidden!r} 的字面量——参数语义只能来自 "
            f"Tool.breadth_args 的声明，硬编码即域内容泄漏进域无关运行时。"
        )


# ══════════════════════════════════════════════════════════════════════════
# Tool.identity_args 与「未声明时行为不变」
# ══════════════════════════════════════════════════════════════════════════
class _Args(BaseModel):
    pass


def _tool(**kw) -> Tool:
    async def _h(args: _Args) -> str:
        return "ok"

    return Tool(name="t", description="d", args_schema=_Args, handler=_h, **kw)


def test_tool_without_declaration_keeps_all_args_as_identity():
    """缺省空集 → 全部参数皆身份，行为与引入本字段前完全一致（安全侧）。"""
    t = _tool()
    assert t.breadth_args == frozenset()
    assert t.identity_args({"a": 1, "window": "6h"}) == {"a": 1, "window": "6h"}


def test_tool_identity_args_strips_declared_breadth():
    t = _tool(breadth_args=frozenset({"window", "limit"}))
    assert t.identity_args({"term": ["x"], "env": "prod", "window": "6h", "limit": 50}) == {
        "term": ["x"], "env": "prod"
    }


def test_real_tools_declarations():
    """域侧声明：vlog_query 的 window/limit、search_knowledge 的 top_k。

    ⚠ 同时钉住 env / term / query MUST NOT 被当成宽度——那会把正当枚举与改写漂移
    误判成打转。
    """
    from domains.appointment.tools.knowledge import search_knowledge
    from domains.oncall.tools.vlog import vlog_query

    assert vlog_query.breadth_args == frozenset({"window", "limit"})
    assert "env" not in vlog_query.breadth_args and "term" not in vlog_query.breadth_args
    assert search_knowledge.breadth_args == frozenset({"top_k"})
    assert "query" not in search_knowledge.breadth_args


# ══════════════════════════════════════════════════════════════════════════
# 与护栏的分界：观测看得见，护栏仍然不拦（本 change 拍定的范围）
# ══════════════════════════════════════════════════════════════════════════
def test_guardrail_still_does_not_catch_this_pattern():
    """★ 范围守卫：同一批换参调用——**信号命中、而护栏仍判不打转**。

    这不是缺陷，是人审拍定的范围：终止循环是生产行为变更，而预约域评测网是知情放弃的
    弱网（41 条、只存点估计无 CI），误杀没有网兜。先让机制看得见，再依据攒到的真实数据
    决定是否拦。

    所以**那 3 分钟白等还会发生**——本 change 只让它可见可计数。这条测试就是防止有人
    读完收尾结论以为"打转问题解决了"，也防止实现悄悄越界去改护栏。
    """
    from harness.guardrails.budget import SpinDetector

    windows = ["2d", "30m", "7d"]
    calls_per_step = [
        [{"name": "vlog_query", "args": {"term": [FAKE_ID], "env": "prod", "window": w, "limit": 50}}]
        for w in windows
    ]

    # 护栏：逐步喂进去，全程判不出打转（参数计入签名 → 连击永远回到 1）。
    spin = SpinDetector(repeat_limit=3)
    assert [spin.check(c) for c in calls_per_step] == [False, False, False]

    # 观测：同一形状的 span，信号命中。
    spans = [_root()] + [
        _step(i, [_call("vlog_query", c[0]["args"], VLOG_BREADTH)])
        for i, c in enumerate(calls_per_step, start=1)
    ] + [_reply_step(4)]
    assert SIGNAL in detect_bad_signals(spans)


def test_signature_semantics_unchanged():
    """`_signature` 未被改动：参数仍计入签名（本 change 明确不动它）。"""
    from harness.guardrails.budget import _signature

    a = _signature([{"name": "vlog_query", "args": {"term": ["x"], "window": "6h"}}])
    b = _signature([{"name": "vlog_query", "args": {"term": ["x"], "window": "2d"}}])
    assert a != b, "参数仍应计入签名——改它属护栏行为变更，不在本 change 范围内"
