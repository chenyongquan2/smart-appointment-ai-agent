# LangChain LCEL `|` 写法 学习笔记

> 围绕 `agents/task_classification/task_classifier.py` 中
> `self.chain = self.prompt | self.llm` 的写法整理而成。
> 适合 LangChain 初学者。

---

## 一、背景代码

```python
# 在 __init__ 里组装（task_classifier.py:26）
self.chain = self.prompt | self.llm

# 在 classify_task 里执行（task_classifier.py:65）
category_msg = await self.chain.ainvoke({"task": task})
category = category_msg.content.strip().lower()
```

---

## 二、核心知识点

### 1. `|` 不是按位或，而是「运算符重载」

Python 允许任何类自定义「被 `|` 操作时怎么办」，靠的是特殊方法 `__or__`：

```python
a | b   ⟺   a.__or__(b)
```

LangChain 的 PromptTemplate、LLM 等都继承自 **Runnable**，Runnable 内部定义了
`__or__`，所以它们能用 `|` 连接。

> 同类机制：`3 + 5` 其实是 `(3).__add__(5)`；`+ - * | &` 都能被类重载。

### 2. `prompt | llm` 是「语法糖」，等价于构造函数写法

```python
self.prompt | self.llm
        ⟺
RunnableSequence(self.prompt, self.llm)
```

- `prompt.__or__(llm)` 内部就是 new 了一个 `RunnableSequence` 返回。
- 两种写法**跑出来的对象、行为完全一致**。

### 3. 「组装」和「执行」是两个不同时刻 ⭐（最容易混淆）

| | `self.chain = self.prompt \| self.llm` | `await self.chain.ainvoke({...})` |
|---|---|---|
| 本质 | **只是赋值**，组装管道 | **真正运行**管道 |
| 时机 | `__init__` 时，只跑一次 | 每次 `classify_task` 调用时 |
| 有输入数据吗 | 没有 | 有（`{"task": ...}`） |
| prompt/llm 跑了吗 | **没跑** | 跑了 |
| 比喻 | 写好菜谱 / 搭好管道 | 照菜谱做菜 / 往管道放水 |

**要点**：赋值那行什么都没执行，只是把「执行计划」打包存起来，以便反复使用。

### 4. 执行时的数据流：前一个的输出 = 后一个的输入

`await self.chain.ainvoke(输入)` 跑起来等价于：

```python
中间结果 = await self.prompt.ainvoke(输入)   # 先跑 prompt：填模板
最终结果 = await self.llm.ainvoke(中间结果)   # 再跑 llm：用上一步输出当输入
```

具体数据流：

```
{"task": "我要预约8号工作人员1小时的推拿"}
        │ self.prompt.ainvoke(...)        ← 第1步：填模板
        ▼
"你是一个服务预约系统的助手...任务内容：我要预约8号工作人员1小时的推拿"
        │ self.llm.ainvoke(...)           ← 第2步：调大模型
        ▼
AIMessage(content="appointment")
        │ .content.strip().lower()
        ▼
"appointment"
```

### 5. 数据流方向 = 类执行时的行为，不是写法决定的 ⭐

`RunnableSequence` 内部简化实现：

```python
class RunnableSequence:
    def __init__(self, *steps):
        self.steps = steps               # 按顺序存：(prompt, llm, ...)

    async def ainvoke(self, 输入):
        结果 = 输入
        for step in self.steps:          # 按存的顺序逐个跑
            结果 = await step.ainvoke(结果)  # 前一个输出喂给后一个
        return 结果
```

**关键认识**：

- `RunnableSequence(prompt, llm)` 和 `prompt | llm` **数据流完全相同**——顺序都由
  「参数/操作数的先后」决定。
- `|` 并没有「多出」数据流，只是**符号长得像箭头/管道，视觉上更直观**；构造函数的
  顺序信息藏在「这个类按参数顺序执行」的语义里。
- 类比：`3 + 5` 和 `add(3, 5)` 都是加法，`+` 只是更直观的写法。

---

## 三、`ainvoke` vs `invoke`

- `ainvoke` = **a**sync invoke（异步），所以前面要加 `await`。
- 因为调用大模型走网络、有等待，异步可以在等待时让程序去做别的事，提高并发效率。
- 同步版是 `invoke`（不用 `await`）。

---

## 四、为什么 `|` 成为主流写法

部件越多，`|` 越有优势：

```python
chain = prompt | llm | output_parser | post_process
```

1. **像数据流**：左→右一眼看出执行顺序（同 Linux 管道 `cat | grep | sort`）。
2. **易拼装复用**：`base = prompt | llm`，再 `base | parserA`、`base | parserB`。
3. **省心**：不用 import、不用记类名 `RunnableSequence`。
4. **官方标准**：LCEL 生态、文档、社区示例几乎全用 `|`，必须会读。

> 但 `RunnableSequence(...)` 可读性也很好、调试更显式，初学时可以心里把
> `a | b` 翻译成 `RunnableSequence(a, b)` 来理解。

---

## 五、一句话记忆

| 概念 | 记忆点 |
|------|--------|
| `\|` 是什么 | 运算符重载，`a \| b` = `a.__or__(b)` |
| 等价写法 | `prompt \| llm` ⟺ `RunnableSequence(prompt, llm)` |
| 赋值 vs 执行 | `= ... \| ...` 只组装；`.ainvoke()` 才运行 |
| 数据流 | 前一个的输出 = 后一个的输入（执行时由顺序决定） |
| `ainvoke` | 异步执行，要 `await` |
