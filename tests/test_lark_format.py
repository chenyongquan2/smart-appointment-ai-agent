"""markdown → 飞书富文本的归一（change: feishu-channel-integration）。

实测暴露的问题：Agent 输出 markdown，用 ``msg_type=text`` 发出去飞书原样显示 ``**加粗**``
的星号（见群里截图）。飞书的富文本走卡片里的 ``lark_md``，它只认 markdown 的一个子集。

本组把「有损但保守」这条原则钉死：不认的语法降级成认的，**其余原样透传**。宁可少渲染，
不可弄丢内容——Agent 输出格式本就不稳定，转换越复杂越容易在边缘情形把正文改坏。
"""

from __future__ import annotations

import pytest

from channels.lark.format import build_text_card, to_lark_md


# --------------------------------------------------------------------------- #
# 标题降级（lark_md 不认标题）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("# 一级", "**一级**"),
    ("## 二级", "**二级**"),
    ("###### 六级", "**六级**"),
    ("### 带空格的标题  ", "**带空格的标题**"),
])
def test_headings_are_demoted_to_bold(raw, expected):
    assert to_lark_md(raw) == expected


def test_heading_already_bold_is_not_double_wrapped():
    """``### **X**`` 不该变成 ``****X****``。"""
    assert to_lark_md("### **服务咨询**") == "**服务咨询**"


def test_only_line_leading_hash_counts():
    """正文中间的 # 不是标题（比如「问题 #3」），不能动。"""
    assert to_lark_md("这是问题 #3 的说明") == "这是问题 #3 的说明"


def test_headings_inside_multiline_text():
    raw = "开头\n## 服务咨询\n- 查询价格\n## 预约办理\n- 安排时间"

    assert to_lark_md(raw) == "开头\n**服务咨询**\n- 查询价格\n**预约办理**\n- 安排时间"


# --------------------------------------------------------------------------- #
# 原样透传（lark_md 原生支持或可接受的语法）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", [
    "**加粗**",                      # lark_md 原生支持
    "*斜体*",
    "~~删除线~~",
    "[链接](https://example.com)",
    "- 列表项一\n- 列表项二",         # 短横以字面显示，本就是列表的视觉约定
    "普通文本，没有任何标记。",
    "价格是 100 元/次",
])
def test_supported_or_acceptable_syntax_is_untouched(raw):
    assert to_lark_md(raw) == raw


def test_empty_and_whitespace_are_safe():
    assert to_lark_md("") == ""
    assert to_lark_md("\n\n") == "\n\n"


def test_empty_heading_collapses_without_crashing():
    """``###`` 后面没内容时不该产出 ``****``（空加粗在客户端上是个怪符号）。"""
    assert to_lark_md("### ") == ""


# --------------------------------------------------------------------------- #
# 卡片结构
# --------------------------------------------------------------------------- #
def test_card_wraps_normalized_markdown():
    card = build_text_card("### 标题\n**加粗**")

    element = card["elements"][0]
    assert element["tag"] == "div"
    assert element["text"]["tag"] == "lark_md"      # 用经典 div+lark_md，兼容性最稳
    assert element["text"]["content"] == "**标题**\n**加粗**"


def test_card_enables_wide_screen():
    """长回复在桌面端铺满宽度，不挤成窄条。"""
    assert build_text_card("x")["config"]["wide_screen_mode"] is True


def test_card_is_json_serializable():
    """卡片要 json.dumps 后塞进 content 字段，不能含不可序列化对象。"""
    import json

    json.dumps(build_text_card("### 标题\n- 项"), ensure_ascii=False)
