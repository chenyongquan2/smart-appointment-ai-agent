"""OnCall 值守域的装载、只读红线与工具契约（change: oncall-domain-vlog）。

本文件同时是**第 2 期领域包抽象的实检**：装一个全新的域（工具集完全不同、无子 Agent、
权限策略非 allow_all）是否真的不需要改 `harness/` 一行。

全程离线，不触真实端点。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domains import Domain, build_tool_registry, load_domain
from domains.oncall.tools.schemas import LoadReferenceArgs, ReferenceName, VlogQueryArgs
from harness.tools.base import Tool


# --------------------------------------------------------------------------- #
# ① 域装载（五槽位）
# --------------------------------------------------------------------------- #
def test_oncall_domain_loads_with_all_five_slots():
    domain = load_domain("oncall")

    assert isinstance(domain, Domain)
    assert domain.name == "oncall"
    assert {t.name for t in domain.tools} == {
        "vlog_query", "load_reference",
        "locate_service_code", "code_search", "read_source",   # 切片 2 新增
    }
    assert domain.subagents == ()          # 值守是一条连贯推理链，本切片不拆子 Agent
    assert "值守" in domain.system_prompt
    assert callable(domain.policy)
    assert domain.evals_dir.is_dir()       # 第 4 期填


def test_oncall_is_selectable_by_env(monkeypatch):
    monkeypatch.setenv("AGENT_DOMAIN", "oncall")

    assert load_domain().name == "oncall"


def test_switching_domain_does_not_leak_tools():
    """换域要换干净：值守域不该看见预约域的工具，反之亦然。"""
    oncall = {t.name for t in load_domain("oncall").tools}
    appointment = {t.name for t in load_domain("appointment").tools}

    assert oncall & appointment == set()


def test_all_oncall_tools_are_read_only():
    """值守域的工具集本身必须全只读——策略是第二道防线，不是唯一那道。"""
    domain = load_domain("oncall")

    assert all(t.dangerous is False for t in domain.tools)


# --------------------------------------------------------------------------- #
# ② 只读红线（策略硬 enforce）
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_policy_denies_dangerous_tool():
    """★ 本域最关键的一条。

    当前两个工具都是只读，所以这条策略在实际运行中**不会拒绝任何东西**——正因如此
    必须专门造一个 dangerous 工具来测，否则这条红线等于没测过。将来谁往值守域加了
    写操作工具（改配置、重启服务、提 PR），要在分发闸门被拦下。
    """
    from pydantic import BaseModel

    executed = {"hit": False}

    class _Args(BaseModel):
        pass

    async def _handler(args: _Args) -> str:
        executed["hit"] = True
        return "不该执行到这里"

    danger = Tool(
        name="restart_service",
        description="假装重启服务",
        args_schema=_Args,
        handler=_handler,
        dangerous=True,
    )

    domain = load_domain("oncall")
    registry = build_tool_registry(domain)
    registry.register(danger)

    result = await registry.dispatch("restart_service", {})

    assert executed["hit"] is False, "危险工具的 handler 绝不能被执行"
    assert "只读" in str(result)


@pytest.mark.asyncio
async def test_policy_allows_read_only_tools():
    """只读工具正常放行——策略不能把正常工作也拦了。"""
    domain = load_domain("oncall")
    registry = build_tool_registry(domain)

    # 用非法入参触发校验错误：能走到 Pydantic 校验，就说明已越过权限闸门。
    with pytest.raises(Exception) as exc:
        await registry.dispatch("vlog_query", {})

    assert "只读" not in str(exc.value)


def test_appointment_domain_policy_is_unaffected():
    """值守域的严格策略不该影响预约域（域之间互不干扰）。"""
    from harness.guardrails.permission import allow_all

    assert load_domain("appointment").policy is allow_all


# --------------------------------------------------------------------------- #
# ③ 工具入参契约
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kwargs", [
    {},                                              # 三者都没给
    {"term": ["a"], "logsql": "x"},                  # 给了两个
    {"term": ["a"], "url": "http://x"},
    {"term": ["a"], "logsql": "x", "url": "http://x"},
])
def test_query_forms_are_mutually_exclusive(kwargs):
    with pytest.raises(ValidationError):
        VlogQueryArgs(**kwargs)


@pytest.mark.parametrize("kwargs", [
    {"term": ["4026299"]},
    {"logsql": 'kubernetes.pod_ip:"10.1.2.3"'},
    {"url": "https://vl.example.com/select/vmui/?#/?query=x"},
])
def test_each_single_query_form_is_valid(kwargs):
    assert VlogQueryArgs(**kwargs)


def test_limit_is_capped_by_schema():
    """样本上限在 schema 层封顶：模型不能要一万条把上下文撑爆。"""
    assert VlogQueryArgs(term=["a"], limit=200)
    with pytest.raises(ValidationError):
        VlogQueryArgs(term=["a"], limit=201)
    with pytest.raises(ValidationError):
        VlogQueryArgs(term=["a"], limit=0)


def test_tool_schema_contains_no_credential_fields():
    """★ 凭据绝不进模型上下文——schema 里不该有任何地址/账号/密码字段。"""
    schema = VlogQueryArgs.model_json_schema()
    names = set(schema["properties"])

    for forbidden in ("user", "username", "password", "auth", "token", "host", "vm_logs_url"):
        assert forbidden not in names


def test_time_zone_trap_is_documented_in_schema():
    """时区坑必须写在 description 里——那是模型构造入参时唯一会读的地方。"""
    schema = VlogQueryArgs.model_json_schema()
    start_desc = schema["properties"]["start"]["description"]

    assert "UTC" in start_desc
    assert "北京" in start_desc


def test_vlog_query_description_carries_the_hard_won_rules():
    """查询经验必须在 description 里，否则模型看不到、等于没移植。"""
    from domains.oncall.tools import vlog_query

    desc = vlog_query.description
    assert "正则" in desc              # 别上 ~ 正则
    assert "时间窗" in desc            # 时间窗是头号杠杆
    assert "样本" in desc              # hits vs returned
    assert "逐字" in desc              # vmui 链接逐字复制
    assert "VPN" in desc               # 不武断归因


# --------------------------------------------------------------------------- #
# ④ 排查资料按需加载
# --------------------------------------------------------------------------- #
def test_every_registered_reference_has_a_file():
    """枚举与文件必须同步——不然改名后要到运行期才炸。"""
    from domains.oncall.tools.reference import REFERENCES_DIR

    missing = [n.value for n in ReferenceName if not (REFERENCES_DIR / f"{n.value}.md").is_file()]

    assert not missing, f"这些资料已登记但文件缺失：{missing}"


def test_reference_name_rejects_free_path():
    """★ 入参是受限枚举而非自由路径——自由路径等于给模型任意文件读取能力。"""
    for evil in ("../../../../etc/passwd", "domains/oncall/policy", "ocs-service-profiles.md"):
        with pytest.raises(ValidationError):
            LoadReferenceArgs(name=evil)


@pytest.mark.asyncio
async def test_load_reference_returns_content():
    from domains.oncall.tools import load_reference

    result = await load_reference.run({"name": "ocs-service-profiles"})

    assert result["name"] == "ocs-service-profiles"
    assert len(result["content"]) > 1000


def test_routing_table_is_in_the_prompt_but_content_is_not():
    """路由表（分诊用）进提示，资料本体不进——97KB 全塞上下文既贵又稀释注意力。"""
    domain = load_domain("oncall")

    for name in ReferenceName:
        assert name.value in domain.system_prompt, f"分诊表漏了 {name.value}"
    # 提示保持在合理量级，说明本体确实没被塞进去
    assert len(domain.system_prompt) < 8000


def test_prompt_carries_the_behavioural_red_lines():
    """跨工具的行为策略在 prompt 里（与 description 分工，见 design D3）。"""
    prompt = load_domain("oncall").system_prompt

    assert "只读" in prompt
    assert "VPN" in prompt                 # 失败不武断归因
    assert "不要查日志" in prompt           # 清单类问题直接读档案
    assert "漂移" in prompt                # 环境漂移被动触发


# --------------------------------------------------------------------------- #
# ⑤ 第 2 期抽象的实检
# --------------------------------------------------------------------------- #
def test_loading_oncall_needed_no_harness_change():
    """装一个全新的域没有让 harness 长出域名分支——领域包抽象成立的证据。

    与 test_domain_loading 的同名检查互补：那条查的是"有没有分支"，这条的意义在于
    **它是在真有第二个域之后跑的**——此前那条检查是空真的。
    """
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'==\s*["\'](?:appointment|oncall)["\']')
    offenders = [
        str(p.relative_to(repo))
        for p in (repo / "harness").rglob("*.py")
        if "__pycache__" not in p.parts and pattern.search(p.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"harness/ 出现了按域名分支：{offenders}"


# --------------------------------------------------------------------------- #
# ⑥ 工具 handler 的三种给法归一
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handler_routes_three_query_forms(monkeypatch):
    """term / logsql / url 三种给法都归一成 LogsQL 交给 service——归一逻辑不在工具层写。"""
    import domains.oncall.tools.vlog as tool_mod
    import services.vlog as svc

    captured: list[dict] = []

    async def fake_query(logsql, **kw):
        captured.append({"logsql": logsql, **kw})
        return svc.QueryResult(ok=True, logsql=logsql, mode="discovery")

    monkeypatch.setattr(svc, "query_logs", fake_query)

    await tool_mod.vlog_query.run({"term": ["4026299", "update_account"]})
    await tool_mod.vlog_query.run({"logsql": 'kubernetes.pod_ip:"10.1.2.3"', "env": "prod"})
    url = svc.build_vmui_url("https://vl.example.com", "2", '"boom"', range_input="3h", limit=50)
    await tool_mod.vlog_query.run({"url": url})

    assert captured[0]["logsql"] == '"4026299" AND "update_account"'   # 多词 → 引号精确 AND
    assert captured[1]["logsql"] == 'kubernetes.pod_ip:"10.1.2.3"'    # 原样透传
    assert captured[2]["logsql"] == '"boom"'                           # 从 fragment 解析出来
    assert captured[2]["env"] == "uat"                                 # accountID=2 → uat
    assert captured[2]["window"] == "3h"                               # 链接自带时间窗
    assert captured[2]["limit"] == 50


@pytest.mark.asyncio
async def test_handler_does_not_guess_env_for_shared_account(monkeypatch):
    """租户 0 同时对应 dev 与 stg，无法反推唯一 env → 返回 None 并发探两者，**不猜**。

    这与「日志里没有的东西就是没查到」是同一条纪律：宁可多查一个环境，也不编一个。
    """
    import domains.oncall.tools.vlog as tool_mod
    import services.vlog as svc

    captured: list[dict] = []

    async def fake_query(logsql, **kw):
        captured.append(kw)
        return svc.QueryResult(ok=True, logsql=logsql, mode="discovery")

    monkeypatch.setattr(svc, "query_logs", fake_query)
    url = svc.build_vmui_url("https://vl.example.com", "0", "x")

    await tool_mod.vlog_query.run({"url": url})

    assert captured[0]["env"] is None


# --------------------------------------------------------------------------- #
# ⑦ 主 Agent 的工具面随域的结构变（冒烟发现的缺陷，补守卫）
# --------------------------------------------------------------------------- #
def test_domain_without_subagents_exposes_tools_directly():
    """★ 无子 Agent 的域，工具必须直接进主 registry。

    冒烟时发现的真缺陷：此前装配写死「主 registry 只放 delegate」，装上值守域会得到
    一个「只有 delegate、却无处可派」的主 Agent——域的两个工具**够不着，且不报错**。
    """
    from domains import build_main_registry

    def _should_not_be_called():
        raise AssertionError("无子 Agent 的域不该构造 delegate")

    registry = build_main_registry(load_domain("oncall"), _should_not_be_called)

    assert set(registry.names()) == {t.name for t in load_domain("oncall").tools}
    assert len(registry.names()) == 5


def test_domain_with_subagents_keeps_delegate_only():
    """有子 Agent 的域维持原形状：主 Agent 只做「派给谁」的决策。"""
    from domains import build_main_registry
    from harness.tools.base import Tool
    from pydantic import BaseModel

    class _A(BaseModel):
        pass

    async def _h(a: _A) -> str:
        return ""

    fake_delegate = Tool(name="delegate", description="d", args_schema=_A, handler=_h)
    registry = build_main_registry(load_domain("appointment"), lambda: fake_delegate)

    assert registry.names() == ["delegate"]


def test_main_registry_carries_the_domain_policy():
    """两种形状都要接上域的权限策略——别在这条分支上把红线丢了。"""
    from domains import build_main_registry

    registry = build_main_registry(load_domain("oncall"), lambda: None)

    assert registry._permission is load_domain("oncall").policy
