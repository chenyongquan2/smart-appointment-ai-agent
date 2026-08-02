from .base import SessionManager
from .repositories import (
    TechnicianRepository,
    UserBehaviorRepository,
    ConversationRepository,
    ConversationSummaryRepository,
    ChannelSessionRepository,
)
from typing import Optional


class DatabaseRouter:
    """
    数据库路由器
    
    职责：
    1. 管理数据库连接和会话
    2. 提供统一的数据访问入口
    3. 协调各个Repository的操作
    """
    
    def __init__(self, db_path: str = 'sqlite:///data/smart_appointment.db'):
        """
        初始化数据库路由器
        
        Args:
            db_path: 数据库连接路径
        """
        self.session_manager = SessionManager(db_path)
        
        # 初始化各个Repository
        self.technician_repo = TechnicianRepository(self.session_manager)
        self.user_behavior_repo = UserBehaviorRepository(self.session_manager)
        self.conversation_repo = ConversationRepository(self.session_manager)
        self.conversation_summary_repo = ConversationSummaryRepository(self.session_manager)
        self.channel_session_repo = ChannelSessionRepository(self.session_manager)

    @property
    def technicians(self) -> TechnicianRepository:
        """获取技师数据仓库"""
        return self.technician_repo

    @property
    def user_behavior(self) -> UserBehaviorRepository:
        """获取用户行为数据仓库"""
        return self.user_behavior_repo

    @property
    def conversations(self) -> ConversationRepository:
        """获取会话历史数据仓库"""
        return self.conversation_repo

    @property
    def summaries(self) -> ConversationSummaryRepository:
        """获取会话摘要缓存数据仓库"""
        return self.conversation_summary_repo

    @property
    def channel_sessions(self) -> ChannelSessionRepository:
        """获取 IM 渠道会话映射数据仓库"""
        return self.channel_session_repo

    def close(self):
        """关闭数据库连接"""
        self.session_manager.close()


# 为了兼容性，保留原有的类名
class TechnicianDBRouter:
    """
    技师数据库路由器（兼容性类）
    
    为保持向后兼容，继续支持原有的接口
    """
    
    def __init__(self, db_type='local', **kwargs):
        self.db_router = DatabaseRouter(**kwargs)
        self.technician_repo = self.db_router.technicians

    # 技师相关方法
    def add_technician(self, name, gender=None, strength=None) -> None:
        return self.technician_repo.add_technician(name, gender, strength)

    def get_technician_by_name(self, name: str):
        return self.technician_repo.get_technician_by_name(name)

    def get_technician_by_id(self, technician_id: int):
        return self.technician_repo.get_technician_by_id(technician_id)

    def get_all_technicians(self):
        return self.technician_repo.get_all_technicians()

    def get_all_strengths(self):
        return self.technician_repo.get_all_strengths()

    # 排班相关方法
    def add_schedule(self, technician_id: int, start_time, end_time, status, appointment_id=None) -> None:
        return self.technician_repo.add_schedule(technician_id, start_time, end_time, status, appointment_id)

    def get_technician_schedules(self, technician_id: int, date):
        return self.technician_repo.get_technician_schedules(technician_id, date)

    def is_technician_available(self, technician_id: int, start_time, end_time) -> bool:
        return self.technician_repo.is_technician_available(technician_id, start_time, end_time)

    def get_technicians_by_gender(self, gender: str):
        return self.technician_repo.get_technicians_by_gender(gender)


class UserBehaviorDBRouter:
    """
    用户行为数据库路由器（兼容性类）
    
    为保持向后兼容，继续支持原有的接口
    """
    
    def __init__(self, db_type='local', **kwargs):
        self.db_router = DatabaseRouter(**kwargs)
        self.user_behavior_repo = self.db_router.user_behavior

    def record_behavior(self, user_id: str, action_type: str, action_data=None, technician_id=None, session_id=None) -> int:
        return self.user_behavior_repo.record_behavior(user_id, action_type, action_data, technician_id, session_id)

    def get_user_behaviors(self, user_id: str, action_type=None, days_back=None):
        return self.user_behavior_repo.get_user_behaviors(user_id, action_type, days_back)

    def get_user_preferences(self, user_id: str):
        return self.user_behavior_repo.get_user_preferences(user_id)

    def update_user_preference(self, user_id: str, preference_type: str, preference_value: str, confidence_score: int = 1) -> bool:
        return self.user_behavior_repo.update_user_preference(user_id, preference_type, preference_value, confidence_score)
