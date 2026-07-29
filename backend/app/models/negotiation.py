"""多 Agent 资源协商域模型 —— 让"资源锁"真正跨请求存在。

背景
----
``resource_negotiation_service`` 原先把资源锁放在 ``self._locks`` 这个
**每请求新建的实例字典**里。FastAPI 每个请求都会 ``ResourceNegotiationService(db)``
一次，于是上一个请求刚拿到的锁，在下一个请求里查不到 —— 这让
"多 Agent 资源协商"的宣称在真实调用链上站不住脚。

本模块补上缺失的持久化层，只新增两张表，不修改任何既有表：

  - ``ResourceLockRecord``  资源锁（协商赢家对资源的占用，带过期时间）
  - ``ResourceBid``         资源竞价（各事件提交的出价，供冲突检测与复盘）

与执行资源审核的分工
------------------
**备件类**资源只记录协商锁，实际可用性在工单审核阶段人工确认
（那是库存域的权威口径，含 ``qty_reserved`` 联动）；本表只负责**协商语义**
（谁赢了、赢了多久、凭什么赢）。两者通过同一个 ``lock_id`` 串起来，
``ResourceLockRecord.reservation_lock_id`` 即指向 ``PartReservation.lock_id``。

人员 / 工具 / 天气窗口这类**没有库存表**的资源，则完全由本表承载锁语义。

表由启动时 ``Base.metadata.create_all`` 自动创建（见 ``app/main.py`` lifespan）。
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    func,
)

from app.database import Base


#: 资源锁状态
RESOURCE_LOCK_STATUSES = ("held", "released", "expired", "preempted")

#: 资源类型 —— 与 ``ResourceRequest.resource_type`` 对齐
RESOURCE_TYPES = ("spare_part", "personnel", "tool", "weather_window")

#: 竞价状态
BID_STATUSES = ("pending", "won", "lost", "withdrawn", "expired")


class ResourceLockRecord(Base):
    """资源锁 —— 一次协商产生的、跨请求可见的独占占用。

    ``resource_id`` 是自由文本句柄（如 ``SP-BRG-001`` / ``maintenance_tech_l3``），
    因为协商域要同时覆盖备件、人员、工具、天气窗口四类异构资源，
    强行做外键反而会把人员/天气这类没有主数据表的资源排除在外。

    ``expires_at`` 到期即视为失效（读取时惰性过期，见
    ``ResourceNegotiationService._expire_stale_locks``），避免某个事件
    拿了锁却再也不释放，把资源永久占死。
    """

    __tablename__ = "resource_locks"

    id = Column(Integer, primary_key=True, index=True)
    lock_id = Column(String(64), unique=True, nullable=False, index=True)
    resource_id = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(32), default="spare_part", index=True)
    incident_id = Column(String(64), nullable=True, index=True)   # 业务编号 INC-xxxx
    incident_pk = Column(Integer, nullable=True, index=True)      # incidents.id（可解析时回填）
    work_order_id = Column(Integer, nullable=True, index=True)
    holder = Column(String(64), nullable=True)                    # 持有方（agent / 用户名）
    quantity = Column(Integer, default=1)
    priority_score = Column(Float, default=0.0)                   # 中标时的竞价分
    status = Column(String(16), default="held", index=True)       # RESOURCE_LOCK_STATUSES
    reason = Column(Text, nullable=True)                          # 中标理由（可解释）
    reservation_lock_id = Column(String(64), nullable=True, index=True)  # → PartReservation.lock_id
    locked_at = Column(DateTime(timezone=True), default=func.now(), index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    released_at = Column(DateTime(timezone=True), nullable=True)


class ResourceBid(Base):
    """资源竞价 —— 一个事件对某资源的出价记录。

    落库的意义有两个：

    1. **冲突检测**：``check_conflicts`` 要能回答"现在还有谁在抢这个资源"，
       没有落库的竞价在下一个请求里就消失了，也就无从检测；
    2. **可复盘**：中标/落标理由与分项得分留痕，是"多 Agent 协商"能被
       第三方复核的前提。
    """

    __tablename__ = "resource_bids"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), unique=True, nullable=False, index=True)
    resource_id = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(32), default="spare_part", index=True)
    incident_id = Column(String(64), nullable=True, index=True)
    incident_pk = Column(Integer, nullable=True, index=True)
    quantity = Column(Integer, default=1)
    urgency = Column(String(16), default="medium")
    economic_impact_per_hour = Column(Float, default=0.0)
    safety_risk = Column(Float, default=0.0)
    max_wait_hours = Column(Float, default=24.0)
    bid_score = Column(Float, default=0.0, index=True)
    score_breakdown = Column(Text, nullable=True)   # JSON 字符串：分项得分
    status = Column(String(16), default="pending", index=True)  # BID_STATUSES
    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
