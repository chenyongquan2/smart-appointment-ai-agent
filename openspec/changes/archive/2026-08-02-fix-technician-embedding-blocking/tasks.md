## 1. 加异步版相似度匹配（旧实现仍在，可对照验证）

- [x] 1.1 `services/text_embedding.py` 新增 `afind_best_match_indices(text, candidates) -> list[int]`：用 `aembed_input` + `asyncio.gather` 并发取查询与全部候选的向量，其余（FAISS `IndexFlatL2` 建索引、`index.search`、返回索引序列）与同步版保持一致。空候选列表仍返回 `[]`。
- [x] 1.2 在 docstring 里写明两件事：① 为什么是 `gather` 而非 `for ... await`（后者不冻循环但延迟 N 倍，可能撞上工具超时）；② `gather` 按**传入顺序**返回而非完成顺序，这是索引位与候选下标对应、排序结果不变的前提。
- [x] 1.3 ✅ 对照已做，但方式与计划不同：实现时同步版被一并替换掉了，故改为**拿 git HEAD 里的原算法逐行照抄进临时脚本**做对照——4 组查询 × 5 个候选，索引序列逐条一致，空候选均返回 `[]`。永久守卫由 5.3 的「排序不变」用例承担（对照脚本是一次性的，未入库）。

## 2. 异步化 TechnicianFinder（只改沾 embedding 的三个）

- [x] 2.1 `filter_technicians_by_preference` 改 `async def`，内部 `await afind_best_match_indices(...)`。
- [x] 2.2 `find_similar_available_technician` 改 `async def`，同上（`technician_finder.py:98`）。
- [x] 2.3 `find_technician_with_thought` 改 `async def`，对上面两个方法加 `await`（`:242` 与指定技师不可用分支）。
- [x] 2.4 确认 `parse_time_and_duration` / `filter_technicians_by_gender` / `find_specific_technician` / `find_available_technician` **保持同步**（无远程 I/O，见 design D4），不做无谓传染。

## 3. 两个调用方改 await

- [x] 3.1 `harness/tools/technician.py:39`：`return await finder.find_technician_with_thought(appointment_history, yield_func=None)`。
- [x] 3.2 `agents/appointment/appointment_processor.py:226`：`tech = await self.technician_finder.find_technician_with_thought(...)`（所在的 `handle_complete_appointment` 已是 async generator，无需再改签名）。
- [x] 3.3 全仓搜一遍 `find_technician_with_thought` / `filter_technicians_by_preference` / `find_similar_available_technician`，确认没有第三个调用方漏改（漏改会得到一个未 await 的协程对象——真值恒 True，可能悄悄"成功"返回假技师）。

## 4. 删死代码并修正错误的 docstring

- [x] 4.1 删同步版 `find_best_match_indices`（改造后零调用方）；同步移除 `services/__init__.py` 的导出与 `__all__` 条目，改为导出 `afind_best_match_indices`。
- [x] 4.2 修 `embed_input` docstring 里那句**错话**——"本函数只应用于确实不在事件循环关键路径上的同步调用点，如 `find_best_match_indices`"。那个例子恰恰是反例、正是本缺陷的源头。改为写明：当前无生产调用方，保留它是作为"为什么必须有异步版"的可执行对照（见 design D3），并记下教训：判断是否在事件循环关键路径，要沿调用链查到入口，不能只看直接调用者。

## 5. 回归测试（守住这条路径）

- [x] 5.1 新建 `tests/test_technician_matching_nonblocking.py`。**核心用例**：注入永不返回的 fake embeddings，起心跳协程，断言 `find_technician_with_thought`（或直接 `afind_best_match_indices`）挂起期间心跳跑满。必须带 `@pytest.mark.timeout`——改回同步实现时这条**不会失败而会挂死**，基于 asyncio 的超时救不了自己（见 design D5）。
- [x] 5.2 **并发用例**：N 个候选的向量化并发发起，整体耗时约 1 轮而非 N 轮（防止有人"异步化"成串行 `for ... await`）。
- [x] 5.3 **排序不变用例**：固定向量下返回的索引序列与预期一致。
- [x] 5.4 用变异验证这几条测试真的能拦住回归：临时把实现改回同步 / 改回串行，确认对应用例分别挂死（被 `pytest-timeout` 判失败）与失败；验证完改回来。
- [x] 5.5 改 `tests/test_harness_tools.py:80` 的 `FakeFinder`——被替换的方法要改成 async，否则 `await` 一个普通返回值会报错。

## 6. 验证与收尾

- [x] 6.1 `uv run pytest` 全绿——成功静默、只报错。特别注意 `tests/test_appointment_agent.py` 与 `tests/test_harness_tools.py`（签名变化会直接打在它们身上）。
- [x] 6.2 冒烟：带力度偏好的预约请求走一遍 `find_technician`，确认仍返回技师、结果与改前一致。
- [x] 6.3 `git diff --stat` 复核 `evals/cases.jsonl`、`evals/baseline.json` 未被改动（本变更不改行为、不需重定基线）。
- [x] 6.4 更新记忆 `rag-eval-deferred`：把"解耦只兑现一半"那段改为已补齐——`appointment` 类不再冻循环（仍会打网关，但失败得干净、可取消）。
