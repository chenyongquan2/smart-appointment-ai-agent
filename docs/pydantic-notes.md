# Pydantic 学习笔记

> 围绕 [harness/tools/schemas.py](../harness/tools/schemas.py) 与 [harness/tools/base.py](../harness/tools/base.py#L52)
> 中 `validated = self.args_schema(**raw_args)` 一句整理而成。
> 适合 Pydantic 初学者。配套：[读源码 · 第 2 站工具层](./harness-code-reading.md)。

---

## 一、一句话

**Pydantic 是一个 Python 库，用「类」来定义「数据应该长什么样」，然后自动帮你校验和转换数据。** 那个类就叫 **Pydantic 模型（model）**。

### 一眼看懂它在干嘛

```python
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int

u = User(name="小明", age="18")   # age 传的是字符串
print(u.age, type(u.age))         # 18 <class 'int'>  ← 自动转成 int
User(name="小明", age="十八")      # ❌ 抛 ValidationError：无法转 int
```

定义一个类、写上字段类型，Pydantic 就自动帮你**校验**（不合法就报错）+ **转换**（`"18"`→`18`）。全篇讲的都是这件事的细节。

本项目用的是 **Pydantic v2**（核心校验器用 Rust 写的 `pydantic-core`，`model_json_schema()` 是 v2 写法；v1 是 `schema()`）。

---

## 二、为什么工具层需要它

LLM 返回的工具调用参数，本质是一坨**不可信的字典**：

```python
{"query": "周末营业吗", "top_k": "3"}   # top_k 是字符串 "3"，不是数字
```

直接用会有一堆问题：类型不对、缺字段、多字段、`top_k=999` 拖垮系统。手写 `if/else` 校验啰嗦又易漏。Pydantic 把**校验 + 类型转换 + 报错**全自动化了。

---

## 三、本项目的实际代码

[schemas.py](../harness/tools/schemas.py) 里每个工具的入参就是一个 Pydantic 模型：

```python
from pydantic import BaseModel, Field

class SearchKnowledgeArgs(BaseModel):        # 继承 BaseModel 即成为 Pydantic 模型
    query: str = Field(description="用户的检索问题文本。")
    top_k: int = Field(default=3, ge=1, le=20, description="返回数量，默认 3。")
    category: str | None = Field(default=None, description="可选分类过滤。")
```

| 写法 | 含义 |
|---|---|
| `class ...(BaseModel)` | 继承 `BaseModel`，获得校验能力 |
| `query: str` | 类型声明——必须是字符串，Pydantic 据此校验 |
| `top_k: int = Field(default=3, ge=1, le=20)` | int；不填默认 3；必须 `1 ≤ top_k ≤ 20` |
| `category: str \| None = ...default=None` | 可为字符串、也可不填（None） |
| `Field(description=...)` | 字段说明——**这段会进 LLM 的上下文**，不是普通注释 |

> `default="未知"` 这类设计（见 `FindTechnicianArgs`）让模型在信息不全时也能调用工具，是给「对话式槽位填充」留的余地。

---

## 四、和 dict / dataclass 的区别

在深入代码细节前，先看清 Pydantic 到底比「裸 dict」「dataclass」多了什么：

| | 普通 dict | dataclass | **Pydantic 模型** |
|---|---|---|---|
| 类型声明 | 无 | 有（但不强制） | 有，**运行时强制校验** |
| 自动转换 | ❌ | ❌ | ✅ `"3"`→`3` |
| 约束（范围/格式） | 手写 if | 手写 | ✅ `ge/le/正则` 等 |
| 导出 JSON Schema | ❌ | ❌ | ✅ `model_json_schema()` |

最后一行最关键：`model_json_schema()` 把模型**自动变成 JSON Schema**，正是 [registry.py:104](../harness/tools/registry.py#L104) 喂给 LLM 的 tools schema 来源——这一点第七节细讲。

---

## 五、`validated = self.args_schema(**raw_args)` 相当于什么

两个知识点叠在一起：`self.args_schema` 是个**类**，`**raw_args` 是**字典解包**。

1. **`self.args_schema` 是类本身**。[base.py](../harness/tools/base.py) 里类型是 `type[BaseModel]`，即「一个类」（如 `SearchKnowledgeArgs`），不是实例。Python 里类是可调用的，`类(...)` = 创建实例 = 调 `__init__`。

2. **`**raw_args` 把字典铺成关键字参数**：

```python
raw_args = {"query": "周末营业吗", "top_k": "3"}
self.args_schema(**raw_args)
# 等价于 ↓
SearchKnowledgeArgs(query="周末营业吗", top_k="3")
```

3. **合起来**，这一句 = 「用这堆数据实例化这个模型」，构造过程中校验 + 转换一并完成。结果 `validated` 是个对象，之后用 `validated.query` / `validated.top_k` 访问。

> 一句话：`类(**字典)` = 「拿字典里的数据去实例化这个类」。Pydantic 模型的实例化 = 校验 + 转换 + 构造，三合一。这就是第一节 `User` 例子在工具层的真实版本。

---

## 六、Pydantic 如何「自动」做到（背后机制）

> 🔧 **进阶 · 第一遍可跳过**：本节讲 Pydantic「为什么能自动校验」的内部原理（元类、Rust 校验器）。看不懂不影响理解后面的内容，可直接跳到第七节。

关键：**校验逻辑不是实例化时临时写的，而是「定义类的那一刻」就提前编译好了。** 分两个时刻。

### 时刻 A · 定义 class 时（import 那一刻，只发生一次）

`BaseModel` 背后有个**元类（metaclass）** `ModelMetaclass`——「创造类的类」，在类定义瞬间介入：

1. 读取类型注解 `__annotations__` → `{"query": str, "top_k": int, ...}`
2. 读取每个 `Field` 的 default / `ge` / `le` / description 等约束
3. 编译出一份内部「核心校验 schema」，挂为 `__pydantic_validator__`（由 Rust 的 `pydantic-core` 编译，故快）

> 类比：定义类 = 提前按图纸造好一台质检机器；实例化 = 把数据丢进去跑一遍。机器只造一次。

### 时刻 B · 实例化时（每次 `args_schema(**raw_args)`）

`BaseModel.__init__` 概念上等价于：

```python
def __init__(self, **data):
    self.__pydantic_validator__.validate_python(data)   # 调那台「质检机器」
```

`validate_python` 逐字段按时刻 A 的规则跑：

| 字段 | 输入 | 校验器做的事 |
|---|---|---|
| `query` | `"周末营业吗"` | 是 str ✅ |
| `top_k` | `"3"` | 目标 int → 转换 `"3"`→`3` ✅ → 查 `1≤3≤20` ✅ |
| `category` | 缺失 | 有 `default=None` → 填 None ✅ |

- 任一字段失败 → 收集**所有**错误 → 抛 `ValidationError`（一次性报全，不是遇错即停）
- 全过 → 转换后的值赋给实例属性

### 时间线

```
import 模块（一次）
  └─ class SearchKnowledgeArgs(BaseModel)
       └─ ModelMetaclass 介入
            ├─ 读 __annotations__ + Field 约束
            └─ 编译 __pydantic_validator__（Rust 校验器，挂在类上）

每次 dispatch（多次）
  └─ self.args_schema(**raw_args)
       └─ BaseModel.__init__
            └─ __pydantic_validator__.validate_python(raw_args)
                 ├─ 逐字段：校验 + 类型强制转换 + 填默认值
                 ├─ 有错 → raise ValidationError
                 └─ 全过 → 赋值实例属性 → 返回 validated
```

所谓「自动」= 元类在定义类时读了类型注解、提前编译了一个 Rust 校验器，实例化时调它。没有魔法，只是把工作提前到「定义类」那一刻。

### 调试时可亲眼看到时刻 A 的产物

```python
SearchKnowledgeArgs.model_fields            # 解析出的字段定义（含约束、default）
SearchKnowledgeArgs.__pydantic_validator__  # 编译好的校验器对象
SearchKnowledgeArgs.model_json_schema()     # 导出的 JSON Schema（喂给 LLM 那份）
```

---

## 七、为什么这对本项目是「单一真相源」

承接第四节的 `model_json_schema()`：一份 Pydantic 模型在本项目里同时承担**三个角色**，改一处三处一致、不漂移：

1. **分发前校验入参**（[base.py:52](../harness/tools/base.py#L52)）
2. **导出给 LLM 的 tools schema**（[registry.py:92](../harness/tools/registry.py#L92) `to_openai_schema` → `model_json_schema()`）
3. **handler 收到的类型安全对象**

```
Pydantic 模型 (schemas.py)
   └─ model_json_schema()  →  JSON Schema（含 description、ge/le、default）
        └─ to_openai_schema()  →  {type:function, function:{name, description, parameters}}
             └─ AgentLoop.__init__ 里 llm.bind_tools(...)  →  绑定给模型
                  └─ 模型推理时「看到」每个工具的名字、说明、参数契约
```

所以你在 schemas.py 写的每句 `description`，最终都进了模型上下文。**工具描述就是给模型的说明书**——这是 Pydantic 在本项目里超出「校验」之外的真正价值。

---

## 八、Pydantic 和 LLM / LangChain / LangGraph 是什么关系

**一句话：Pydantic 本身和它们没有「依赖」关系，但它是这个生态事实上的「标准胶水层」。**

### Pydantic 是独立的

Pydantic 是个**通用数据校验 / 序列化库**（2017 年就有，远早于 LLM 热潮），最初主要用在 Web 后端——FastAPI 就建立在它之上。**它不依赖任何 LLM，LLM 也不强制需要它。**

### 但为什么和 LLM 生态绑得很紧

LLM 输出的是**文本**。要把文本变成可靠、程序能用的结构化数据，需要两件事——而 Pydantic 一个库同时解决：

| 环节 | Pydantic 的作用 |
|---|---|
| 告诉 LLM 要什么形状 | `Model.model_json_schema()` 生成 JSON Schema，塞进 tool 定义或提示词 |
| 校验 LLM 吐回来的 JSON | `Model.model_validate(...)` 解析成带类型的对象，不合法直接报错 |

这正是本笔记第六~七节讲的同一套机制，只是换个视角：**对内**校验工具入参，**对外**当 LLM 的 schema 说明书。

### 各家怎么用它

| 框架 / SDK | 用 Pydantic 做什么 |
|---|---|
| **LangChain** | `llm.with_structured_output(MyModel)`、`PydanticOutputParser`、工具调用参数 schema |
| **LangGraph** | 图的 **State** 可用 Pydantic 模型定义（也可用 `TypedDict`）；节点结构化输出 |
| **OpenAI / Anthropic SDK** | tool/function calling 的参数就是 JSON Schema，通常由 Pydantic 生成 |
| **PydanticAI / Instructor** | 专为「LLM 结构化输出」而造；PydanticAI 还是 Pydantic 团队自己出的 |

### 和本项目的关系

正好对应 `CLAUDE.md` 的核心约定:**「结构化输出 > 字符串解析」**。本项目没直接用 LangChain 的 `with_structured_output`，而是手动走 `model_json_schema()` → `to_openai_schema()` → `bind_tools()`（见第七节),把同一份模型既当校验器、又当 LLM 的 schema——和上面这些框架是同一个套路,只是没套框架的壳。

> 总结：Pydantic 本可以和 LLM 毫无关系；但因为它「定义 schema + 校验数据」两件事最顺手，整个 LLM/Agent 生态把它当成了连接「自然语言」与「类型化代码」的标准桥梁。
