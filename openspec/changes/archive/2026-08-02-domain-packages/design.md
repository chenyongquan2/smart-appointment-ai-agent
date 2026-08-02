## Context

三处运行时组装点各自 `import` 域内容并手工拼装：

| 位置 | 现在怎么拼 |
|---|---|
| `api/chat_handler.py:50-79` | `build_default_registry()` + `build_default_subagent_registry()` + `build_system_prompt()` |
| `evals/agent_capture.py:47-70` | 同款三件套（`_build_capture_loop`） |
| 各测试 | 零散调用上面两个工厂 |

两个 `build_default_*` 工厂的**函数体里写死了域内容**（`from harness.tools.appointment import create_appointment` 等），`BASE_SYSTEM_PROMPT` 则直接写着"你是一家按摩/推拿门店的智能助手"。这就是本期要拆的三处硬编码。

一个容易看漏的事实：`harness/guardrails/permission.py` 的闸门**在生产路径上从未被接过**（`api/chat_handler.py` 一处 `policy=` 都没有，走 `ToolRegistry` 的 `allow_all` 默认）。所以"权限策略"这个槽位不是"搬过去"，是**第一次有归属地**。

## Goals / Non-Goals

**Goals:**
- 域内容与域无关运行时彻底分离，边界由目录结构强制而非靠自觉。
- 装域靠配置，运行时代码对"当前是哪个域"无知。
- 为第 3 期的 oncall 域留好五个可填的槽位（尤其是权限策略——oncall 的只读红线要靠它硬 enforce）。
- 顺手还清 `harness/tools/` → `agents/` 的横向依赖债，并删掉 pre-harness 遗留层。

**Non-Goals:**
- **不改任何行为**。这是纯搬迁 + 接线重排；工具的 name/description/args_schema、子 Agent 的工具子集、system prompt 文本、权限判定结果一律不变。
- 不实现 oncall 域（第 3 期）。
- 不扩用例、不重定基线（见预约域评测冻结决策）。
- 不做插件式动态发现（`entry_points` / 目录扫描）——见 D2。

## Decisions

### D1 `Domain` 是一个 frozen dataclass，不是基类

```python
@dataclass(frozen=True)
class Domain:
    name: str
    tools: tuple[Tool, ...]
    subagents: tuple[SubAgent, ...]
    system_prompt: str          # 域人设与红线（原 BASE_SYSTEM_PROMPT 的位置）
    policy: PermissionPolicy    # 权限策略，默认 allow_all
    evals_dir: Path             # 用例集与 baseline 的所在
```

**为什么不是抽象基类**：域是**一份声明**，不是一组行为——它没有需要子类覆写的方法。项目里同类东西（`Tool`、`SubAgent`）都是 frozen dataclass，保持一致。frozen 还保证装载后没人能偷偷往 registry 里塞工具。

**为什么工具是 `tuple` 而不是已建好的 `ToolRegistry`**：registry 的组装方式因场景而异（主 registry 只含 `delegate`、子 Agent 各持工具子集、评估要独立 exporter 沙盒），域只负责"我有哪些工具"，怎么装是运行时的事。域交出 registry 会越界。

### D2 装载靠显式注册表，不做动态发现

```python
_DOMAINS = {"appointment": load_appointment_domain}   # name -> 无参工厂

def load_domain(name: str | None = None) -> Domain:
    name = name or os.getenv("AGENT_DOMAIN", "appointment")
    ...  # 未知域名抛明确错误，列出可选值
```

考虑过按 `domains/` 目录扫描或 `entry_points` 自动发现，都否决了：本项目一共会有 **2 个域**，动态发现换来的是"哪个域被装载了"变得不可静态推断、import 副作用时机不确定、以及打错域名时的报错从"明确列出可选值"退化成"什么都没发生"。显式字典 3 行代码，一眼看得出全集。

**工厂是函数而非模块级实例**：域包内含重型 import（工具 handler 会延迟拉起 services）。装 A 域时不该把 B 域的依赖也拉起来——这在第 3 期尤其重要，oncall 域会拖着 VictoriaLogs / git worktree 那些东西。

### D3 `AGENT_DOMAIN` 环境变量，缺省 `appointment`

缺省值保证**本次改造零配置即行为不变**：不设环境变量的部署（含所有测试、CI）自动装预约域，与今天完全一致。第 3 期给 oncall 部署设 `AGENT_DOMAIN=oncall` 即可，两套部署共用一份代码。

放弃过的替代方案：写进 `config/` 的 Python 常量（改域要改代码、不能一份代码跑两实例）；命令行参数（channel 是长连接常驻进程，没有天然的 argv 入口）。

### D4 `build_system_prompt` 接收域提示，而不是自己知道域

签名从 `build_system_prompt(registry, subagents)` 改为 `build_system_prompt(base_prompt, registry, subagents)`。函数本身（拼接工具说明书、渲染子 Agent 清单）是纯域无关逻辑，**留在 harness**；域人设文本移到 `domains/appointment/prompt.py`。

这是本期唯一的公开签名变更，三处组装点都要跟着改。**刻意选显式传参而不是让函数内部去 `load_domain()`**：后者会让一个纯函数变成依赖全局状态的函数，测试要靠打桩环境变量才能改提示——那是把"域无知"做成了"域隐形"，更难查。

### D5 权限策略：把隐式的 `allow_all` 写成显式，并接上线

`domains/appointment/policy.py` 明写 `POLICY = allow_all`，装载时传给 `ToolRegistry(policy=...)`。

**判定结果一字不变**（今天走的就是 `allow_all` 默认），所以这仍在"纯搬迁"范围内。但它把一条**从未被验证过的接线**打通了——第 3 期 oncall 声明只读策略时，如果那时才发现 registry 根本没接 policy，红线就成了纸面约定。宁可在纯搬迁这一期把管道通了、留一条测试守着。

### D6 `TechnicianFinder` 下沉到 `services/technician_matching.py`，不进域包

它是"按专长/性别/时间匹配技师"的**业务逻辑**，按项目分层该在 `services/`；`domains/appointment/tools/technician.py` 只是它的薄封装。放进域包会让域包同时装"工具"和"业务实现"两种东西，与 `services/` 的既有职责重叠。

搬迁时**只改 import 与文件位置，不动函数体**——它刚在 `fix-technician-embedding-blocking` 里改成 async，同一批代码短期内两次改动，混在一起会让 `git log` 说不清是谁引入的问题。

顺带删掉 `harness/tools/technician.py` 模块 docstring 里那段"本工具临时横向依赖 `agents/`，违反严格的单向向下，Phase 3 迁移后即可去除"——这次兑现了。

### D7 evals 数据集移入域包，运行器留在 `evals/`

`domains/appointment/evals/{cases.jsonl,baseline.json}`；`evals/` 下的 `run_evals.py` / `agent_capture.py` / `trace_collect.py` / `triage.py` 等**全部域无关，原地不动**，改为从当前装载的域读取数据路径。

这正是「机制 ≠ 数据」那条判断的落地：域绑定的只有两个数据文件，机制一行不用改。第 4 期建 oncall 用例集时，往 `domains/oncall/evals/` 放两个文件即可。

**文件内容一字不改**（含 `baseline.json` 里那些 mojibake 的中文指标名）——改路径的同时改内容，就没法证明是纯搬迁了。

### D8 搬迁的验证方式：不改断言

搬迁若需要修改任何**行为断言**，就说明它不是纯搬迁。允许改的只有 import 路径与装配代码。收尾对照：

```bash
uv run pytest        # 443 passed / 9 xfailed —— 数字必须一致
```

⚠ 但要诚实：pytest 用 fake LLM，**不会推理"该调哪个工具"**。工具层结构变了而"模型仍选对工具"这件事，pytest 验不了。按冻结决策不为此投入新数据工作，至多跑一次现有 `--gate`。**验收结论应表述为"pytest 全绿、选工具正确性未验证"**，不是"全绿即证明无损"。

## Risks / Trade-offs

- **[大范围移动文件，diff 噪声淹没真实改动]** → 缓解：分两个提交——先纯 `git mv` + 改 import（可用 `--find-renames` 看清），再改装配逻辑。评审时先看第二个提交。
- **[三处组装点漏改一处]** → 缓解：删掉 `build_default_registry` / `build_default_subagent_registry` 而不是留兼容壳——漏改的地方会直接 ImportError，而不是悄悄用着旧的写死工厂。
- **[域包与 harness 的边界判断错，把域无关的东西也搬走]** → 判据：**这段代码换成 oncall 域还成立吗？** 成立就留 harness（如 `build_system_prompt` 的拼接逻辑、`SubAgent` 结构），不成立才进域包（如"你是一家按摩门店的智能助手"）。
- **[删遗留层误伤活路径]** → 缓解：先下沉 `TechnicianFinder` 并跑绿，再删 `agents/`；`api/chat_handler.py` 与 `channels/lark/` 不引用 `agents/`（已查）。

## Migration Plan

1. `services/technician_matching.py` 下沉，`harness/tools/technician.py` 改指向它 → 跑绿。
2. 建 `domains/` 骨架与 `Domain` / `load_domain`，预约域五槽位填齐（此时旧工厂仍在）→ 新增装载测试。
3. 三处组装点切到 `load_domain()`，删两个旧工厂 → 跑绿。
4. 删 `agents/` 遗留层与两个遗留端点 → 跑绿。
5. evals 数据文件移入域包，运行器改读域路径 → 跑绿。

**回滚**：单分支 `git revert`；无数据侧动作（`baseline.json` 只换位置不换内容）。

## Open Questions

- 第 3 期 oncall 的 `mt_docs_search` 与现有 `search_knowledge`（`KnowledgeSearchPort`）是否合并成一个工具——本期不决定，但域包结构对两种选择都开放。
