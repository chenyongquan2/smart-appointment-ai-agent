"""事件去重（change: feishu-channel-integration，tasks 3.4）。

**这不是性能优化，是防重复副作用的唯一防线。** `create_appointment` 目前没有幂等键，
重复消费一次事件就是真的多下一单。飞书在网络抖动时会重投同一 event_id，所以这一层
MUST 有；将来若给危险工具加了幂等键，它才降级成"锦上添花"。

内存实现的取舍：飞书的重投窗口是分钟级，进程内 TTL 集合足够；写 DB 的收益低于成本。
代价是进程重启后表清空，存在极小概率的重复消费——这条残余风险显式记在 design 的
Risks 里，不假装不存在。

⚠ 另一个前提：去重表是**进程内**的，故服务 MUST 单 worker 运行。多 worker 会起多份
长连接、各自持有独立的去重表，同一条消息被不同进程各消费一次，这一层拦不住。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable

DEFAULT_TTL_SECONDS = 300.0   # 5 分钟，覆盖飞书重投窗口
DEFAULT_MAX_ENTRIES = 10_000  # 容量上限，防长期运行下内存无界增长


class TTLDedup:
    """带 TTL 与容量上限的「见过没」集合。

    Args:
        ttl_seconds: 条目存活时长；超时即视为没见过。
        max_entries: 容量上限；超出时淘汰最旧条目（FIFO）。
        clock: 单调时钟，测试可注入假时钟以免真等。
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        # OrderedDict 而非 set：要按插入顺序淘汰最旧的，还要记每条的时间戳做 TTL 判定。
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def is_new(self, key: str) -> bool:
        """首次见到该 key 返回 ``True`` 并记录；重复则返回 ``False``。

        「判定 + 记录」合成一个原子动作是刻意的：拆成 `contains` + `add` 两步，调用方
        很容易在中间提前 return 而漏掉记录，于是重复事件被反复处理。
        """
        now = self._clock()
        self._evict_expired(now)

        if key in self._seen:
            return False

        self._seen[key] = now
        # 容量兜底：TTL 只在有新事件进来时才驱逐，短时洪峰下可能先撑破容量。
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)  # last=False → 弹出最早插入的
        return True

    def _evict_expired(self, now: float) -> None:
        """从最旧一端起清理过期条目。

        因为 OrderedDict 按插入顺序排列、TTL 又是固定值，所以一旦碰到未过期的条目，
        它之后的必然也都没过期——可以立刻停下，不必扫全表。
        """
        deadline = now - self._ttl
        while self._seen:
            key, stamp = next(iter(self._seen.items()))
            if stamp > deadline:
                return
            self._seen.pop(key, None)

    def __len__(self) -> int:
        return len(self._seen)
