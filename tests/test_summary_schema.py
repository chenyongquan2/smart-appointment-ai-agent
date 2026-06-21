"""ConversationSummary schema 单测（add-context-compaction：记忆压缩）。

离线、无网络、无 LLM 依赖。验证字段默认值与 render 输出包含各关键段。
详见 OpenSpec change: add-context-compaction。
"""

from harness.memory.summary_schema import ConversationSummary


def test_defaults_are_empty_lists():
    s = ConversationSummary()
    assert s.key_entities == []
    assert s.decisions == []
    assert s.open_items == []
    assert s.user_constraints == []


def test_render_empty_returns_empty_string():
    assert ConversationSummary().render() == ""


def test_render_includes_all_nonempty_sections():
    s = ConversationSummary(
        key_entities=["张伟技师", "推拿"],
        decisions=["已确认周六 14:00 推拿"],
        open_items=["待用户确认时长"],
        user_constraints=["只要女技师", "只能周末"],
    )
    text = s.render()

    # 各段标题与内容都应出现。
    assert "用户约束/偏好" in text and "只要女技师" in text and "只能周末" in text
    assert "已做决定" in text and "已确认周六 14:00 推拿" in text
    assert "待办/未确认" in text and "待用户确认时长" in text
    assert "关键实体" in text and "张伟技师" in text


def test_render_omits_empty_sections():
    s = ConversationSummary(user_constraints=["只要女技师"])
    text = s.render()

    assert "用户约束/偏好" in text and "只要女技师" in text
    # 空的段不应出现标题。
    assert "已做决定" not in text
    assert "待办/未确认" not in text
    assert "关键实体" not in text
