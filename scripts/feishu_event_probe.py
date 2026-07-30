"""飞书事件载荷探针（一次性诊断工具，change: feishu-channel-integration tasks 3.2）。

**为什么需要它**：设计里要把飞书的一次对话映射成 Agent 的 ``session_id``，会话键的首选是
``thread_id``。但 ``thread_id`` 只在**开启了话题模式的群**里下发，普通群 @ 机器人的消息
大概率只有 ``chat_id`` / ``message_id`` / ``root_id``——这是基于 API 文档的判断，不是实测
结论。而 ``channel_session`` 表一旦写入数据，改会话键定义就要做迁移。

所以本脚本先于建表运行：连上长连接，把收到的事件**原样打出来**，只读不写——不入库、
不回复、不提交任务。看清字段实况后再定会话键。

用法::

    uv run python scripts/feishu_event_probe.py

然后在测试群里 @ 机器人发一条消息。打印完即退出（``--keep`` 可持续监听多条）。
"""

from __future__ import annotations

import argparse
import os
import sys

# Windows 中文控制台默认 gbk，无法编码下面的框线与中文；与 app.py 同款处理。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

import lark_oapi as lark
from dotenv import load_dotenv

load_dotenv()

# 会话键的候选字段——本次探测要看清的就是这几个到底有没有值。
_SESSION_KEY_CANDIDATES = [
    ("message.thread_id", "话题 id（仅话题模式群下发）"),
    ("message.root_id", "回复链根消息 id"),
    ("message.parent_id", "父消息 id"),
    ("message.message_id", "本条消息 id"),
    ("message.chat_id", "群 id"),
]

_OTHER_FIELDS = [
    ("message.chat_type", "群类型（group / p2p）"),
    ("message.message_type", "消息类型（text / post / …）"),
    ("sender.sender_id.open_id", "发送者 open_id（→ user_id，偏好按人隔离）"),
    ("sender.sender_id.union_id", "发送者 union_id"),
    ("sender.sender_id.user_id", "发送者 user_id（需通讯录权限）"),
    ("sender.sender_type", "发送者类型"),
]


def _dig(obj: object, path: str) -> object:
    """按 ``a.b.c`` 逐级取属性；任一级缺失或为 None 即返回 None。"""
    cur = obj
    for part in path.split("."):
        cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _render(event: object, rows: list[tuple[str, str]]) -> None:
    for path, note in rows:
        value = _dig(event, path)
        mark = "✔" if value not in (None, "") else "✘"
        shown = value if value not in (None, "") else "—— 未下发 ——"
        print(f"  {mark} {path:34} {str(shown):42} {note}")


def _report(data: object, keep: bool) -> None:
    header = getattr(data, "header", None)
    event = getattr(data, "event", None)

    print("\n" + "=" * 100)
    print("收到事件")
    print("=" * 100)
    print(f"  event_id   = {getattr(header, 'event_id', None)}")
    print(f"  event_type = {getattr(header, 'event_type', None)}")
    print(f"  create_time= {getattr(header, 'create_time', None)}")

    print("\n【会话键候选】—— 决定 session_id 怎么定义，以及 channel_session 表怎么建")
    _render(event, _SESSION_KEY_CANDIDATES)

    print("\n【其它关键字段】")
    _render(event, _OTHER_FIELDS)

    mentions = _dig(event, "message.mentions")
    print(f"\n【@ 了谁】mentions = {lark.JSON.marshal(mentions) if mentions else '(空)'}")
    print(f"【正文】content = {_dig(event, 'message.content')}")

    print("\n【完整事件载荷（原样）】")
    try:
        print(lark.JSON.marshal(event, indent=2))
    except Exception as exc:  # noqa: BLE001 —— 探针工具，序列化失败也要把能看的看到
        print(f"(序列化失败: {exc!r}；退回 repr)")
        print(repr(event))
    print("=" * 100)

    if not keep:
        print("\n探测完成。按 Ctrl+C 退出（或直接关掉本进程）。")
        print("下一步：据上面的『会话键候选』确定优先级链，再动 tasks 3.3 的建表。")


def main() -> int:
    parser = argparse.ArgumentParser(description="打印飞书消息事件的原始载荷（只读，不回复）")
    parser.add_argument("--keep", action="store_true",
                        help="持续监听多条事件（默认打印后仍驻留，本参数只影响提示文案）")
    args = parser.parse_args()

    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    domain = os.getenv("FEISHU_DOMAIN", lark.FEISHU_DOMAIN)

    if not app_id or not app_secret:
        print("[ERROR] .env 里缺 FEISHU_APP_ID / FEISHU_APP_SECRET。"
              "申请与配置见 docs/feishu-app-setup.md。", file=sys.stderr)
        return 1

    print(f"探针启动：app_id={app_id} domain={domain}")
    print("只读模式——不入库、不回复、不提交任务。")
    print("请在测试群里 @ 机器人发一条消息……（Ctrl+C 退出）\n")

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(lambda data: _report(data, args.keep))
        .build()
    )

    client = lark.ws.Client(
        app_id, app_secret,
        event_handler=handler,
        domain=domain,
        log_level=lark.LogLevel.INFO,
    )
    try:
        # 独立脚本里用同步 start() 没问题；但注意它内部是
        # `loop.run_until_complete(...)`，**不能**直接用在 FastAPI lifespan
        # （那里已有运行中的事件循环）——consumer 要改用 await client._connect()。
        client.start()
    except KeyboardInterrupt:
        print("\n已退出。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
