# tool-layer 规格（delta）

## MODIFIED Requirements

### Requirement: 工具定义结构

每个工具 SHALL 定义在 `harness/tools/` 下的独立文件中（一个概念一个文件），并声明四要素：唯一 `name`（snake_case）、面向模型的 `description`、入参 schema（Pydantic v2 模型）、以及 `handler`（可调用对象）。工具 handler MUST 仅作为 `services/` 的薄封装，不得重写业务逻辑，且 MUST NOT 反向依赖 `agents/` 或 `harness/runtime`。每个工具 SHALL 另外声明一个 `dangerous` 标记（布尔，默认 `False`）以标识其是否为有副作用的危险操作；带副作用的写操作工具（如 `create_appointment`）MUST 标记为 `dangerous=True`，只读查询工具保持默认 `False`。

每个工具 SHALL 另外支持一个可选的 `timeout` 声明（秒，默认 `None`）：`None` 表示采用全局缺省工具超时，显式数值覆盖之，显式声明为不限时则该工具不受超时约束。超时的施加与语义见 `agent-loop` 的「工具失败不崩循环」。

超时声明在工具自身而非运行时全局常量，原因是不同工具的合理耗时相差数量级：`delegate` 的 handler 内部运行的是一整个子 AgentLoop（多步 LLM 调用），与一次本地 DB 查询共用同一个上限必然误杀其一。该设计也使后续接入网络工具时，超时成为工具声明处的自然填空，无需改动运行时。

工具编写约定 SHALL 写明超时的适用边界：超时依赖 `asyncio` 的取消机制，只能中断在 await 点让出控制权的 handler；内部执行同步阻塞调用（同步 SQLite / FAISS / 子进程等）的工具即使声明了 `timeout` 也不会被真正中断，此类工具 MUST 自行将阻塞调用下沉到线程池才能获得超时保护。

#### Scenario: 工具暴露四要素

- **WHEN** 注册中心或测试读取任一已实现工具
- **THEN** 该工具暴露非空 `name`、非空 `description`、一个 Pydantic `BaseModel` 子类作为 args schema、以及一个可调用 `handler`

#### Scenario: 工具为薄封装

- **WHEN** 调用任一工具的 handler
- **THEN** 它将参数转交给对应 `services/` 方法并返回其结果，不包含独立的业务规则实现

#### Scenario: 危险工具被正确标记

- **WHEN** 读取 `create_appointment` 与只读工具（如 `search_knowledge`）的 `dangerous` 标记
- **THEN** `create_appointment` 的 `dangerous` 为 `True`，只读工具的 `dangerous` 为 `False`

#### Scenario: 工具可声明自己的超时

- **WHEN** 读取任一工具的 `timeout` 声明
- **THEN** 未显式声明的工具取值为 `None`（表示采用全局缺省），显式声明的工具取值为其自身设定

#### Scenario: delegate 豁免默认超时

- **WHEN** 读取 `delegate` 工具的 `timeout` 声明
- **THEN** 它显式豁免全局缺省工具超时，不会因默认上限而在子 Agent 正常执行期间被中断
