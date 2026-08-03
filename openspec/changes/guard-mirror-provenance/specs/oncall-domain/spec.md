## MODIFIED Requirements

### Requirement: 源码定位

值守域 SHALL 提供源码定位能力：给定服务名与环境，返回该服务对应环境分支的**本地只读工作区**路径、当前 HEAD 标识与所在分支。

环境到分支的映射 SHALL 按**候选顺序**解析（带环境后缀的分支名优先、裸名兜底），取第一个存在者；全部候选都不存在时 SHALL 返回 `branch_not_found` 状态**并带上已试候选列表**——那个列表是给用户看的依据，缺了它用户无从判断是不是分支命名不同。

仓库尚未在本地就绪时 SHALL 返回 `need_clone` 引导状态，而非抛错——这是可操作的正常分支，不是异常。

工作区 SHALL 为 detached 状态且按「服务 × 环境」常驻复用，MUST NOT 每次分析新建。

**mirror 来源 SHALL 被探测并如实带回。** 本地 mirror 若是从**工作副本**（而非正规远端）clone 出来的，其 `refs/heads/*` 只反映上游开发者本地拉到哪，可能远远落后于真实远端；而定位能力读的正是 `refs/heads/*`。因此：

- 定位能力 SHALL 判定 mirror 来源，并在来源为工作副本时**在结果中明确标出**；
- 来源为工作副本且该分支可解析时，SHALL 一并带回它相对远端跟踪引用**落后的 commit 数**；落后为 0 时仍 SHALL 标出来源，因为那是当下巧合而非配置正确；
- 定位能力 MUST NOT 在探测到可疑来源时**静默返回**这份可能过期的源码——沉默会让使用者基于旧代码下判断，比直接报错危险；
- 定位能力 MUST NOT 自动改读 `refs/remotes/*` 来绕过该问题——绕行会把错误配置隐藏起来，使运维永远不知道 mirror 建错了；
- 来源可疑本身 SHALL NOT 阻断定位：结果仍为 `ready`，判断权交给使用者。

正规远端 clone 出的 mirror（无 `refs/remotes/*` 命名空间）SHALL 不受任何影响。

#### Scenario: 定位到已就绪的工作区

- **WHEN** 给定已在本地就绪的服务与环境
- **THEN** 返回工作区路径、HEAD 标识与解析到的分支名

#### Scenario: 分支不存在时带回已试候选

- **WHEN** 该环境的全部候选分支名都不存在
- **THEN** 返回 `branch_not_found`，且结果中含已尝试的候选分支名列表

#### Scenario: 仓库未就绪时给引导状态

- **WHEN** 该服务的仓库尚未在本地
- **THEN** 返回 `need_clone` 状态与服务名，MUST NOT 抛出异常

#### Scenario: 正规远端建的 mirror 不受影响

- **WHEN** mirror 是从正规远端 clone 的（不含任何 `refs/remotes/*` ref）
- **THEN** 结果中不含任何来源警示字段，行为与本需求变更前完全一致

#### Scenario: 来源为工作副本且分支落后时如实带回落后量

- **WHEN** mirror 含 `refs/remotes/*` ref，且解析到的分支在 `refs/heads/` 下落后于对应的 `refs/remotes/origin/` 引用
- **THEN** 结果状态仍为 `ready`，但含来源可疑标记与**落后的 commit 数**，MUST NOT 无提示地返回该工作区

#### Scenario: 来源为工作副本但恰好同步时仍标出来源

- **WHEN** mirror 含 `refs/remotes/*` ref，且该分支与远端跟踪引用一致（落后 0）
- **THEN** 结果仍标出来源可疑，落后数为 0——因为同步只是当下巧合，上游一落后它就跟着落后

#### Scenario: 分支只存在于远端跟踪引用下时说明真实原因

- **WHEN** 某分支在 `refs/heads/` 下不存在、但在 `refs/remotes/origin/` 下存在
- **THEN** 返回 `branch_not_found` 的同时说明「mirror 来自工作副本、该分支只存在于远端跟踪引用下」，MUST NOT 让使用者误以为仓库里没有这个分支

#### Scenario: 来源警示随工具结果抵达模型

- **WHEN** 定位结果带有来源可疑标记
- **THEN** 返回值中含一条模型可见的人话警示，MUST NOT 只有结构化数字而无说明文本

#### Scenario: 未经定位直接检索源码时警示同样抵达

- **WHEN** 模型不调用定位工具、直接对来源可疑的工作区做源码检索或阅读
- **THEN** 这些工具的返回值中同样含该警示——警示 MUST NOT 只挂在定位这一条路径上，否则半数调用路径仍然静默
