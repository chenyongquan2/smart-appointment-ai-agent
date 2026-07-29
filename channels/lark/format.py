"""把 Agent 的 markdown 输出转成飞书能渲染的形式（change: feishu-channel-integration）。

背景：Agent 产出的是 markdown（``**加粗**``、``- 列表``、``### 标题``）。用 ``msg_type=text``
发出去，飞书**原样显示星号和井号**——实测截图里满屏 ``**服务咨询**``，观感很脏。

飞书的富文本走交互式卡片（``msg_type=interactive``）里的 ``lark_md`` 标签，它支持 markdown
的一个**子集**：加粗 / 斜体 / 删除线 / 链接 / 换行。**不支持标题与嵌套列表**，遇到就原样显示。

所以这里做的是「有损但保守」的归一：把 lark_md 不认的语法降级成它认的（标题 → 加粗），
其余原样透传。刻意不做完整 markdown → 富文本转换——那需要一个解析器，而 Agent 输出的
格式本就不稳定，转换越复杂越容易在边缘情形把内容弄坏。宁可少渲染，不可弄丢内容。
"""

from __future__ import annotations

import re

# 行首 1~6 个 # + 空格 + 标题文字。lark_md 不认标题，降级为加粗（视觉层级最接近）。
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


def to_lark_md(text: str) -> str:
    """把 markdown 归一为 ``lark_md`` 能渲染的子集。

    只做一件事：标题降级成加粗。加粗/斜体/链接 lark_md 原生支持，列表的 ``-`` 会以字面
    短横显示（可接受，本就是列表的视觉约定），故都不动。
    """
    def _demote(match: re.Match[str]) -> str:
        title = match.group(2).strip()
        if not title:
            return ""
        # 已经自带加粗标记的标题不要套两层（``### **X**`` → ``**X**``）。
        if title.startswith("**") and title.endswith("**"):
            return title
        return f"**{title}**"

    return _HEADING.sub(_demote, text)


def build_text_card(text: str) -> dict:
    """构造一个只含文本的交互式卡片。

    用最经典的 ``div`` + ``lark_md`` 组合而不是卡片 2.0 的 ``markdown`` 标签：前者在各版本
    飞书客户端上的兼容性最稳，而本期只需要「能把加粗和换行渲染出来」这一点。
    """
    return {
        # wide_screen_mode：长回复在桌面端铺满宽度，不挤成窄条。
        "config": {"wide_screen_mode": True},
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": to_lark_md(text)}}
        ],
    }
