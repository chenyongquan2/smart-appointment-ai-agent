from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
from datetime import datetime

Base = declarative_base()

class Technician(Base):
    __tablename__ = 'technicians'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    gender = Column(String, nullable=True)      # 新增性别字段
    strength = Column(String, nullable=True)    # 新增力气/倾向性字段
    schedules = relationship("TechnicianSchedule", back_populates="technician", cascade="all, delete-orphan")

class TechnicianSchedule(Base):
    __tablename__ = 'technician_schedules'
    id = Column(Integer, primary_key=True)
    technician_id = Column(Integer, ForeignKey('technicians.id'))
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)  # 'busy' or 'free'
    appointment_id = Column(Integer, nullable=True)
    technician = relationship("Technician", back_populates="schedules")

# 说明：原 KnowledgeDocument（表 knowledge_documents）随本地 RAG 一并移除
# （change: remove-local-rag）。已存在的 SQLite 表刻意**不删、不迁移**——摘掉 ORM 映射后
# 它就是一张无人引用的静态表，而知识库内容今后由独立的 RAG 项目提供。
# 原有的 10 条默认文档抄录在该 change 的 tasks.md 附录 A。

class UserBehavior(Base):
    __tablename__ = 'user_behaviors'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, default='default_user')  # 单用户场景使用默认用户ID
    action_type = Column(String, nullable=False)  # 'appointment', 'consultation', 'inquiry'
    action_data = Column(JSON, nullable=True)  # 存储行为相关的详细数据
    technician_id = Column(Integer, ForeignKey('technicians.id'), nullable=True)
    session_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    technician = relationship("Technician")

class UserPreference(Base):
    __tablename__ = 'user_preferences'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, default='default_user')
    preference_type = Column(String, nullable=False)  # 'technician', 'time', 'service', 'duration'
    preference_value = Column(String, nullable=False)
    confidence_score = Column(Integer, default=1)  # 偏好的置信度（出现次数）
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ConversationTurn(Base):
    """会话对话回合（Phase 4：会话历史持久化）。

    按 ``session_id`` 隔离，每行记录一轮中的一条消息（用户或助手），
    用于进程重启后恢复会话历史。详见 OpenSpec change: phase-4-state-memory。
    """
    __tablename__ = 'conversation_turns'
    id = Column(Integer, primary_key=True)
    session_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ConversationSummary(Base):
    """会话摘要缓存（add-context-compaction：记忆压缩）。

    每个 ``session_id`` 至多一条摘要：把短期窗口外的较旧回合滚动压缩为一段文本，
    供下一轮请求注入上下文。``covered_upto`` 记录"已被压缩进摘要的最后一条
    ``ConversationTurn`` 的 id"，作为滚动/失效的稳定游标（见 design.md D5）。
    """
    __tablename__ = 'conversation_summaries'
    id = Column(Integer, primary_key=True)
    # session_id 唯一：一个会话只保留一条"最新"摘要（滚动 upsert，不堆历史快照）。
    session_id = Column(String, nullable=False, unique=True, index=True)
    summary_text = Column(Text, nullable=False)
    # covered_upto = "这条摘要已经把历史压缩到了哪一条为止" 的书签/游标。
    #   值 = 被压进本摘要的【最后一条 ConversationTurn 的 id】。
    #   语义："covered up to id=X" → 所有 id ≤ X 的回合，其信息都已并入 summary_text。
    #   用途（滚动压缩）：下次压缩时只需处理 id > covered_upto 的「新出窗回合」，
    #     id ≤ covered_upto 的老回合不再重读（它们已在摘要里）。
    #   例：covered_upto=4 表示 1~4 已压缩；当 5~8 又滑出窗口时，只把 5~8 增量并入。
    #   为何用 turn id 而非"第几条"计数：id 单调递增、抗并发，"id 之后即新增"语义稳定。
    covered_upto = Column(Integer, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChannelSession(Base):
    """IM 渠道会话 → Agent 会话的映射（change: feishu-channel-integration）。

    ``external_id`` 存的是**解析后**的会话键，不是原始事件字段。飞书普通群的解析链是
    ``root_id → message_id``（首条 @bot 消息取自身 message_id，其后每条回复的 root_id
    都指回它，于是收敛到同一会话）；``scope='chat'`` 时取 ``chat_id``。
    ⚠ ``thread_id`` **不参与**取键——实测它只出现在续话消息上、首条没有，排在解析链
    首位会让首条与其回复落到不同会话，多轮直接断裂（证据见
    ``docs/evidence/feishu-event-payload-2026-07-29.log``）。

    这张表为何存在（诚实说明）：``session_id`` 本可由 ``external_id`` 确定性派生
    （``feishu:{key}``），所以**正确性并不依赖本表**，进程重启后照样能派生出同一个值。
    表的价值在两点：① 让绑定关系**权威且稳定**——派生规则日后若调整，已建立的会话仍按
    表中记录延续，不会因换规则而集体断档；② 审计与反查，从 ``session_id`` 找回它对应
    群里的哪次对话（第 4 期 oncall triage 要把 trace 关联回真实对话）。
    """

    __tablename__ = 'channel_sessions'
    id = Column(Integer, primary_key=True)
    channel = Column(String, nullable=False)                    # 'feishu' / 将来的 'dingtalk' 等
    scope = Column(String, nullable=False)                      # 'reply' / 'chat'
    external_id = Column(String, nullable=False)                # 解析后的会话键
    session_id = Column(String, nullable=False, index=True)     # 对应的 Agent 会话标识
    created_at = Column(DateTime, default=datetime.utcnow)

    # 同一渠道下一个外部键只能绑一个会话——并发下靠 DB 约束兜底，不只靠应用层先查后写。
    __table_args__ = (
        UniqueConstraint('channel', 'external_id', name='uq_channel_session_external'),
    )


class BadCase(Base):
    """坏 case 回流记录（Phase 6：评估闭环）。

    记录失败或用户纠正的 case，供事后复盘与补充评估集。新增独立表，不改动既有
    业务表语义。``trace_id`` 可关联可观测层的同一次请求 trace。
    详见 OpenSpec change: phase-6-observability。
    """
    __tablename__ = 'bad_cases'
    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False, index=True)  # 'failure' or 'correction'
    user_input = Column(Text, nullable=False)
    expected = Column(Text, nullable=True)
    actual = Column(Text, nullable=True)
    trace_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    extra = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserRecommendation(Base):
    __tablename__ = 'user_recommendations'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, default='default_user')
    recommendation_type = Column(String, nullable=False)  # 'technician_available', 'return_reminder', 'service_suggestion'
    content = Column(Text, nullable=False)
    technician_id = Column(Integer, ForeignKey('technicians.id'), nullable=True)
    is_sent = Column(Integer, default=0)  # 是否已发送
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    technician = relationship("Technician")
