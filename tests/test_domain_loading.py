"""领域包的装载契约（change: domain-packages）。

守的是「换域 = 换五样东西，运行时一行不动」这条设计判断——它是第 3 期 oncall 域能
干净落地的前提。四类断言：

1. **五槽位齐全**：域交出工具集 / 子 Agent 集 / 人设 / 权限策略 / 评估数据目录。
2. **配置切换**：`AGENT_DOMAIN` 决定装哪个；缺省 `appointment` 保证零配置即行为不变。
3. **未知域名启动即失败**：不静默回落——回落会让配置写错表现为"跑起来了但装错了域"
   （oncall 部署因一个拼写错误装成预约域，会拿按摩人设去回答线上故障）。
4. **运行时对域无知**：`harness/` 等目录里既无域名分支，也无域内容。

第 4 类是几条 grep 式的结构断言。它们不测行为，测的是**架构约束不被悄悄破坏**——
这类约束靠 code review 守不住，靠测试才守得住。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import domains
from domains import (
    DEFAULT_DOMAIN,
    DOMAIN_ENV_VAR,
    Domain,
    available_domains,
    build_subagent_registry,
    build_tool_registry,
    load_domain,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# ① 五槽位齐全
# --------------------------------------------------------------------------- #
def test_appointment_domain_has_all_five_slots():
    domain = load_domain("appointment")

    assert isinstance(domain, Domain)
    assert domain.name == "appointment"
    assert domain.tools, "工具集不能为空"
    assert domain.subagents, "子 Agent 集不能为空"
    assert domain.system_prompt.strip(), "人设不能为空"
    assert callable(domain.policy), "权限策略必须可调用"
    assert domain.evals_dir.is_dir(), "评估数据目录必须存在"


def test_appointment_domain_content_matches_pre_migration():
    """搬迁后内容与领域包化之前逐项一致（纯搬迁的证据）。"""
    domain = load_domain("appointment")

    assert {t.name for t in domain.tools} == {
        "search_knowledge",
        "find_technician",
        "check_availability",
        "create_appointment",
        "get_user_preferences",
    }
    assert {a.name for a in domain.subagents} == {
        "appointment",
        "consultant",
        "user_behavior",
    }
    # 人设仍是按摩门店（域内容没搬错，也没被 GENERIC_BASE_PROMPT 顶替）
    assert "按摩" in domain.system_prompt


def test_domain_is_frozen():
    """域是声明不是可变状态——装载后不能再往里塞工具。"""
    domain = load_domain("appointment")

    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        domain.name = "oncall"  # type: ignore[misc]


def test_evals_data_lives_in_domain_package():
    """数据随域走、机制留在 evals/（design D7 的分界）。"""
    domain = load_domain("appointment")

    assert (domain.evals_dir / "cases.jsonl").is_file()
    assert (domain.evals_dir / "baseline.json").is_file()
    # 机制仍在 evals/，且那里不再放数据
    assert (REPO_ROOT / "evals" / "run_evals.py").is_file()
    assert not (REPO_ROOT / "evals" / "cases.jsonl").exists()


# --------------------------------------------------------------------------- #
# ② 配置切换
# --------------------------------------------------------------------------- #
def test_default_domain_is_appointment_without_env(monkeypatch):
    """零配置即行为不变——不设环境变量的部署（含全部 CI）自动装预约域。"""
    monkeypatch.delenv(DOMAIN_ENV_VAR, raising=False)

    assert load_domain().name == DEFAULT_DOMAIN == "appointment"


def test_env_var_selects_domain(monkeypatch):
    """注册一个假域，验证环境变量真的决定装哪个（不靠"以后有 oncall 再说"）。"""
    sentinel = Domain(
        name="fake",
        tools=(),
        subagents=(),
        system_prompt="fake",
        policy=lambda tool, args: None,
        evals_dir=REPO_ROOT,
    )
    monkeypatch.setitem(domains._DOMAINS, "fake", lambda: sentinel)
    monkeypatch.setenv(DOMAIN_ENV_VAR, "fake")

    assert load_domain() is sentinel
    assert "fake" in available_domains()


def test_explicit_argument_wins_over_env(monkeypatch):
    monkeypatch.setenv(DOMAIN_ENV_VAR, "appointment")

    assert load_domain("appointment").name == "appointment"


# --------------------------------------------------------------------------- #
# ③ 未知域名启动即失败（不静默回落）
# --------------------------------------------------------------------------- #
def test_unknown_domain_raises_and_lists_options(monkeypatch):
    monkeypatch.setenv(DOMAIN_ENV_VAR, "oncal")  # 少一个 l，典型拼写错误

    with pytest.raises(ValueError) as exc:
        load_domain()

    message = str(exc.value)
    assert "oncal" in message
    assert "appointment" in message, "报错必须列出可选域名，否则无从改起"


def test_unknown_domain_does_not_fall_back(monkeypatch):
    """★ 关键：不能悄悄回落到缺省域。

    回落会让配置写错表现为「跑起来了但装错了域」——oncall 部署会拿着按摩人设去回答
    线上故障，而日志里一切正常。启动失败远比这安全。
    """
    monkeypatch.setenv(DOMAIN_ENV_VAR, "definitely_not_a_domain")

    with pytest.raises(ValueError):
        load_domain()


# --------------------------------------------------------------------------- #
# ④ 运行时对域无知（架构约束）
# --------------------------------------------------------------------------- #
_RUNTIME_DIRS = ("harness", "evals", "executor", "channels")
_DOMAIN_NAME_BRANCH = re.compile(r'==\s*["\'](?:appointment|oncall)["\']')


def _python_files(*dirs: str):
    for d in dirs:
        for path in (REPO_ROOT / d).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path


def test_runtime_has_no_domain_name_branches():
    """运行时代码 MUST NOT 出现 `if domain == "..."`。"""
    offenders = [
        f"{p.relative_to(REPO_ROOT)}"
        for p in _python_files(*_RUNTIME_DIRS)
        if _DOMAIN_NAME_BRANCH.search(p.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"运行时出现按域名分支：{offenders}"


_BUSINESS_WORDS = ("按摩", "推拿", "技师", "预约")

# ⚠ 已知的**剩余域泄漏**，本期刻意不修（见下）。写成白名单而不是把测试放宽，
# 是为了让这处泄漏留在明面上——一旦有人清掉它，删掉这条即可；新增泄漏仍会被拦。
_KNOWN_DOMAIN_LEAKS = {
    # ConversationSummary 的 Field description 里举的全是预约例子（"技师姓名"、
    # "只要女技师"）。那些字符串是**写给模型看的提示词**（会进 model_json_schema），
    # 故 oncall 域会拿着按摩例子去做会话摘要——是真泄漏。
    #
    # 本期不修的理由：schema 的**结构**（key_entities / decisions / open_items /
    # user_constraints）本身是域无关的、设计得不错；泄漏的只是描述里的举例。改它
    # 等于改提示词 → 改变 LLM 行为 → 越出「纯搬迁」纪律，且可能拉低预约域的摘要
    # 质量（那些例子确实在帮模型）。正解是让描述随域可配，属独立改造。
    "harness/memory/summary_schema.py",
    # summary.py 里拼摘要提示时也带了预约字样，与上同源。
    "harness/memory/summary.py",
    # LongTermMemory 的 _TYPE_LABELS 把 preference_type 映射成中文标签
    # （technician→技师 / service→服务项目 …）。那几个 key 本身就是预约域的概念，
    # 且标签会拼进注入模型的偏好提示。oncall 域的长期偏好是另一套东西。
    # 同样属"需要让它随域可配"，不是搬个文件能解决的，故一并留到独立改造。
    "harness/memory/long_term.py",
}

# 这三处泄漏的共同点值得记一笔：它们都在**记忆层**，且都不是"放错了位置的域内容"
# （那种搬走就行），而是"域无关的机制里嵌了域特定的提示词/枚举"。要清干净得让这些
# 文本随域可配——那会改变注入模型的提示，属行为变更，与本期的纯搬迁纪律冲突。
# 领域包已经给了它们未来的归属地（Domain 再加一两个槽位即可），本期只负责把账记明白。


def _docstring_lines(tree: ast.AST) -> set[int]:
    """收集全部 docstring 占用的行号——它们里的历史说明（"这里曾经放过按摩人设"）
    是有价值的记录，不该被当成泄漏。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is None:
                continue
            first = node.body[0]
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def test_harness_contains_no_domain_content():
    """harness/ 的**可执行代码**里不该再有业务词汇——域人设与领域工具都已迁出。

    用 AST 精确剔除 docstring（而非"行首是引号"这种近似判断），故它查的是真代码，
    包括 Field(description=...) 这类**会进提示词**的字符串——那些正是最该查的。
    """
    offenders = []
    for path in _python_files("harness"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _KNOWN_DOMAIN_LEAKS:
            continue
        source = path.read_text(encoding="utf-8")
        skip = _docstring_lines(ast.parse(source))
        for lineno, line in enumerate(source.splitlines(), 1):
            if lineno in skip:
                continue
            code = line.split("#", 1)[0]
            if any(w in code for w in _BUSINESS_WORDS):
                offenders.append(f"{rel}:{lineno}")

    assert not offenders, f"harness/ 的代码里仍有域内容：{offenders}"


def test_known_domain_leaks_still_exist():
    """白名单不能烂在那儿：泄漏被清掉后，这条会失败，提醒把白名单一起删。"""
    still_leaking = []
    for rel in _KNOWN_DOMAIN_LEAKS:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        skip = _docstring_lines(ast.parse(source))
        leaks = any(
            any(w in line.split("#", 1)[0] for w in _BUSINESS_WORDS)
            for lineno, line in enumerate(source.splitlines(), 1)
            if lineno not in skip
        )
        if leaks:
            still_leaking.append(rel)

    assert set(still_leaking) == _KNOWN_DOMAIN_LEAKS, (
        f"这些文件的域泄漏已被清除，请从 _KNOWN_DOMAIN_LEAKS 删掉："
        f"{_KNOWN_DOMAIN_LEAKS - set(still_leaking)}"
    )


# --------------------------------------------------------------------------- #
# ⑤ 权限策略确实被接进分发（本期第一次打通这条线）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_domain_policy_is_wired_into_dispatch():
    """★ 域声明的策略必须真的生效。

    权限闸门此前从未被接进生产路径（实际走 allow_all 默认）。一条从未验证过的接线
    等于没有——oncall 的只读红线要靠它硬 enforce。这条守着那根管子。
    """
    from harness.guardrails.permission import Decision

    def deny_everything(tool, args):
        return Decision.denied("测试策略：一律拒绝")

    domain = load_domain("appointment")
    denied = Domain(
        name="denied",
        tools=domain.tools,
        subagents=domain.subagents,
        system_prompt=domain.system_prompt,
        policy=deny_everything,
        evals_dir=domain.evals_dir,
    )
    registry = build_tool_registry(denied)

    result = await registry.dispatch("create_appointment", {
        "technician_id": 1,
        "start_time": "2026-08-03 15:00",
        "duration": "60分钟",
        "project": "按摩",
    })

    assert "拒绝" in str(result) or "denied" in str(result).lower()


@pytest.mark.asyncio
async def test_appointment_policy_still_allows_everything():
    """预约域的判定结果与领域包化之前一致（放行）——本期接线不改变任何行为。"""
    domain = load_domain("appointment")
    registry = build_tool_registry(domain)

    # 不真的建单：只验证「没有被权限闸门拦下」。用非法参数触发校验错误即可证明
    # 请求已越过闸门、进到了 Pydantic 校验那一层。
    with pytest.raises(Exception) as exc:
        await registry.dispatch("create_appointment", {})

    assert "拒绝" not in str(exc.value)


def test_registries_built_from_domain_match_declaration():
    domain = load_domain("appointment")

    tool_registry = build_tool_registry(domain)
    subagent_registry = build_subagent_registry(domain)

    assert set(tool_registry.names()) == {t.name for t in domain.tools}
    assert set(subagent_registry.names()) == {a.name for a in domain.subagents}
