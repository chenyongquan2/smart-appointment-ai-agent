## 1. 颗粒度：per-tool 部分给分 P/R/F1（evals/metrics.py）

- [x] 1.1 新增 name 级 per-tool 比对：对每条可评估用例算 `命中=set(actual名)∩set(expected名)`，得 recall=|命中|/|expected|、precision=|命中|/|actual|、F1
- [x] 1.2 跨用例宏平均（每条等权）产出 `工具调用-召回率` / `工具调用-精确率` / `工具调用-F1` 三个 Metric；无可评估样本各自显式 N/A
- [x] 1.3 保留并改名原集合全等指标为 `工具调用-完全匹配率`（全有或全无）作最严对照

## 2. 严格度·参数级（evals/metrics.py）

- [x] 2.1 实现集中的轻量参数归一化函数（统一大小写/数字与字符串等稳定键涉及的类型），加单测
- [x] 2.2 参数级匹配谓词：对一个工具，按 `expected_tool_args[工具名]` **逐键**比（只比标注的键，actual 多出忽略），全键归一化后相等才算该工具参数匹配
- [x] 2.3 产出 `工具调用-参数级F1`：仅对含 `expected_tool_args` 的用例计入，否则该用例 N/A；无任何标注用例时整档 N/A

## 3. 严格度·序列级（evals/metrics.py）

- [x] 3.1 实现子序列匹配：`expected_tools`（有序）是否为 `actual` 名字序列（全局有序）的子序列
- [x] 3.2 产出 `工具调用-序列正确率`（按用例宏平均，每条 0/1）；无可评估样本 N/A

## 4. 报告渲染 + 用例标注

- [x] 4.1 `build_report` / `format_report` 分档展示上述指标（沿用 N/A 注明、成功静默风格），完全匹配率与召回率并列
- [x] 4.2 给 `evals/cases.jsonl` 的 6 条 appointment + 2 条多工具 query 补 `expected_tool_args`（只标稳定键：gender/duration/project/technician）

## 5. 测试 + 验证（闸门 2）

- [x] 5.1 补离线确定性单测：部分给分 P/R/F1 正确（含部分命中）、参数级逐键比（含 actual 多键忽略）、参数归一化、子序列匹配（含多调容忍与逆序判错）、各档缺数据 N/A
- [x] 5.2 `uv run pytest` 全绿（含新测与既有回归），成功静默、只暴露失败
- [x] 5.3 软验收：有 key 时真跑，报告里完全匹配率旁出现有信息量的召回率等分档数字（只看结构，不断言百分比）
- [x] 5.4 确认 out-of-scope 未被牵入（无参数语义/时间等价、无精确偏序、无基线阈值阻断）
