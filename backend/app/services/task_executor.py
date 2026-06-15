"""Task Executor -- maps LLM action plans to real database operations.

This module is the EXECUTE stage of the Task Agent pipeline.
It does NOT call HTTP endpoints -- uses SQLAlchemy directly.
"""

import logging
import re
from typing import Any
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Turbine, WorkOrder, User, Fault, NotificationConfig

logger = logging.getLogger(__name__)

VALID_ACTIONS = frozenset({
    "find_turbine", "list_turbines", "list_work_orders", "create_work_order",
    "send_work_order_email", "update_work_order", "cancel_work_order",
    "list_personnel", "list_faults", "navigate",
})

# Page route mapping for navigation
PAGE_ROUTES = {
    "dashboard": "/dashboard",
    "turbine": "/turbine",
    "diagnosis": "/diagnosis",
    "prediction": "/prediction",
    "workorders": "/workorder",
    "knowledge": "/knowledge",
    "settings": "/settings",
}


class StepExecutionError(Exception):
    """Wraps a step failure with structured context."""

    def __init__(self, step: int, action: str, message: str):
        self.step = step
        self.action = action
        self.message = message
        super().__init__(message)


class TaskExecutor:
    """Executes a list of planned steps against the database sequentially."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._step_outputs: dict[int, Any] = {}

    async def execute(self, steps: list[dict]) -> list[dict]:
        """Run all steps in order. Stops on first failure.

        Returns list of result dicts: {step, action, success, result?, error?}
        """
        results: list[dict] = []
        for plan in steps:
            step_num = plan.get("step", len(results) + 1)
            # Support both "action" and "operation" field names from LLM
            action = plan.get("action") or plan.get("operation") or ""
            raw_params = plan.get("params", {})
            reason = plan.get("reason", "")

            if action not in VALID_ACTIONS:
                results.append({
                    "step": step_num, "action": action,
                    "success": False,
                    "error": f"不支持的操作 '{action}'。支持: {sorted(VALID_ACTIONS)}",
                })
                break

            params = self._resolve_params(raw_params)

            logger.info("TaskExecutor step %d: %s(%s) -- %s", step_num, action, params, reason)

            try:
                handler = getattr(self, f"_do_{action}")
                output = await handler(**params)
                self._step_outputs[step_num] = output
                results.append({
                    "step": step_num, "action": action,
                    "success": True, "result": output,
                })
            except StepExecutionError:
                raise
            except TypeError as e:
                results.append({
                    "step": step_num, "action": action,
                    "success": False,
                    "error": f"参数错误 {action}: {e}",
                })
                break
            except Exception as e:
                logger.exception("Step %d (%s) failed", step_num, action)
                results.append({
                    "step": step_num, "action": action,
                    "success": False,
                    "error": str(e),
                })
                break

        return results

    # ------------------------------------------------------------------
    # Parameter resolution -- supports $step_N.field and $step_N.INDEX.field
    # ------------------------------------------------------------------

    def _resolve_params(self, params: dict) -> dict:
        resolved = {}
        for key, value in params.items():
            resolved[key] = self._resolve_one(value)
        return resolved

    def _resolve_one(self, value: Any) -> Any:
        if not isinstance(value, str) or not value.startswith("$step_"):
            return value
        # Match $step_N, $step_N.field, $step_N.INDEX, $step_N.INDEX.field
        m = re.match(r'\$step_(\d+)(?:\.(\d+))?(?:\.(\w+))?', value)
        if not m:
            return value
        step_num = int(m.group(1))
        index = int(m.group(2)) if m.group(2) is not None else None
        field = m.group(3)
        output = self._step_outputs.get(step_num)
        if output is None:
            raise StepExecutionError(
                step_num, "resolve_ref",
                f"引用的步骤 {step_num} 尚未执行",
            )
        # Array index: $step_1.0.wo_id
        if index is not None:
            if isinstance(output, list) and index < len(output):
                output = output[index]
            else:
                raise StepExecutionError(
                    step_num, "resolve_ref",
                    f"步骤 {step_num} 结果无法按索引 {index} 访问",
                )
        # Field access
        if field:
            if isinstance(output, dict):
                return output.get(field, output)
            raise StepExecutionError(
                step_num, "resolve_ref",
                f"步骤 {step_num} 结果不是字典，无法读取字段 '{field}'",
            )
        return output

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    async def _do_find_turbine(self, name: str) -> dict:
        """Search turbines by name substring, with numeric fallback."""
        result = await self.db.execute(
            select(Turbine).where(Turbine.name.ilike(f"%{name}%"))
        )
        turbines = result.scalars().all()

        if not turbines:
            nums = re.findall(r'\d+', name)
            if nums:
                result = await self.db.execute(
                    select(Turbine).where(Turbine.name.ilike(f"%{nums[0]}%"))
                )
                turbines = result.scalars().all()

        if not turbines:
            raise StepExecutionError(
                0, "find_turbine",
                f'未找到名称匹配 "{name}" 的风机，请确认编号。',
            )

        t = turbines[0]
        if len(turbines) > 1:
            logger.warning("find_turbine: multiple matches for '%s', using first: %s", name, t.name)

        return {
            "turbine_id": t.id,
            "turbine_name": t.name,
            "status": t.status,
            "region": t.region or "",
        }

    async def _do_list_work_orders(
        self, turbine_id: int | None = None, status: str | None = None,
    ) -> list[dict]:
        """List work orders, optionally filtered."""
        q = select(WorkOrder).order_by(WorkOrder.created_at.desc())
        if turbine_id is not None:
            q = q.where(WorkOrder.turbine_id == turbine_id)
        if status:
            q = q.where(WorkOrder.status == status)
        result = await self.db.execute(q)
        wos = result.scalars().all()
        return [
            {
                "wo_id": wo.id,
                "turbine_id": wo.turbine_id,
                "title": wo.title,
                "status": wo.status,
                "assignee": wo.assignee or "",
                "priority": wo.priority or "medium",
                "created_at": wo.created_at.isoformat() if wo.created_at else "",
            }
            for wo in wos
        ]

    async def _do_create_work_order(
        self, turbine_id: int, title: str,
        description: str = "", priority: str = "medium",
    ) -> dict:
        """Create a new work order."""
        t_result = await self.db.execute(
            select(Turbine).where(Turbine.id == turbine_id)
        )
        if not t_result.scalar_one_or_none():
            raise StepExecutionError(
                0, "create_work_order",
                f"风机 ID={turbine_id} 不存在",
            )

        wo = WorkOrder(
            turbine_id=turbine_id,
            title=title,
            description=description or None,
            priority=priority,
            status="pending",
        )
        self.db.add(wo)
        await self.db.commit()
        await self.db.refresh(wo)

        logger.info("Created work order WO-%04d: %s", wo.id, wo.title)
        return {
            "wo_id": wo.id,
            "title": wo.title,
            "status": wo.status,
            "turbine_id": wo.turbine_id,
        }

    async def _do_send_work_order_email(self, wo_id: int) -> dict:
        """Send work order email to the current assignee."""
        result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            raise StepExecutionError(0, "send_work_order_email",
                                     f"工单 WO-{wo_id:04d} 不存在")

        if not wo.assignee:
            raise StepExecutionError(0, "send_work_order_email",
                                     f"工单 WO-{wo_id:04d} 尚未分配负责人，请先使用 update_work_order 分配。")

        user_result = await self.db.execute(
            select(User).where(
                User.username == wo.assignee,
                User.is_active == True,
            )
        )
        user = user_result.scalar_one_or_none()
        if not user or not user.email:
            raise StepExecutionError(
                0, "send_work_order_email",
                f"负责人 {wo.assignee} 的邮箱未配置",
            )

        cfg_result = await self.db.execute(
            select(NotificationConfig).where(NotificationConfig.user_id == user.id)
        )
        cfg = cfg_result.scalar_one_or_none()
        if not cfg or not cfg.email_enabled:
            raise StepExecutionError(
                0, "send_work_order_email",
                f"负责人 {wo.assignee} 未开启邮件通知，请先在系统设置中启用。",
            )

        from app.services.email_service import send_email, EmailConfigError

        subject = f"[风调预顺] WO-{wo.id:04d} {wo.title}"
        body = (
            f"工单编号: WO-{wo.id:04d}\n"
            f"工单标题: {wo.title}\n"
            f"风机ID: {wo.turbine_id}\n"
            f"当前状态: {wo.status}\n"
            f"责任人: {wo.assignee}\n"
            f"优先级: {wo.priority or 'medium'}\n\n"
            f"请及时登录风调预顺 PHM 系统查看并处理该工单。"
        )

        try:
            await send_email(user.email, subject, body)
        except EmailConfigError as e:
            raise StepExecutionError(0, "send_work_order_email",
                                     f"邮件服务未配置: {e}") from e

        wo.notification_sent_at = datetime.now(timezone.utc)
        await self.db.commit()

        return {
            "wo_id": wo.id,
            "title": wo.title,
            "sent_to": user.email,
            "recipient": wo.assignee,
        }

    async def _do_update_work_order(
        self, wo_id: int,
        status: str | None = None,
        assignee: str | None = None,
    ) -> dict:
        """Update work order status and/or assignee."""
        VALID_STATUSES = {"pending", "assigned", "in_progress",
                          "review", "completed", "closed", "cancelled"}

        result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            raise StepExecutionError(0, "update_work_order",
                                     f"工单 WO-{wo_id:04d} 不存在")

        if status is not None:
            if status not in VALID_STATUSES:
                raise StepExecutionError(
                    0, "update_work_order",
                    f"无效状态 '{status}'。有效值: {', '.join(sorted(VALID_STATUSES))}",
                )
            wo.status = status
            if status == "completed":
                wo.completed_at = datetime.now(timezone.utc)
            if status == "cancelled":
                wo.cancelled_at = datetime.now(timezone.utc)

        if assignee is not None:
            user_check = await self.db.execute(
                select(User).where(
                    User.username == assignee,
                    User.is_active == True,
                )
            )
            if not user_check.scalar_one_or_none():
                raise StepExecutionError(
                    0, "update_work_order",
                    f"负责人 '{assignee}' 不存在或已禁用",
                )
            wo.assignee = assignee
            if wo.status == "pending":
                wo.status = "assigned"

        await self.db.commit()
        await self.db.refresh(wo)

        return {
            "wo_id": wo.id,
            "title": wo.title,
            "status": wo.status,
            "assignee": wo.assignee or "",
        }

    async def _do_cancel_work_order(self, wo_id: int) -> dict:
        """Cancel a work order."""
        result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            raise StepExecutionError(0, "cancel_work_order",
                                     f"工单 WO-{wo_id:04d} 不存在")

        if wo.status == "cancelled":
            return {"wo_id": wo.id, "title": wo.title, "status": "cancelled",
                    "note": "工单已经是取消状态"}

        wo.status = "cancelled"
        wo.cancelled_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(wo)

        return {"wo_id": wo.id, "title": wo.title, "status": wo.status}

    async def _do_list_personnel(self) -> list[dict]:
        """List all active technicians with current workload."""
        user_result = await self.db.execute(
            select(User)
            .where(User.is_active == True, User.role == "technician")
            .order_by(User.username.asc())
        )
        users = user_result.scalars().all()

        personnel = []
        for u in users:
            load_result = await self.db.execute(
                select(func.count(WorkOrder.id)).where(
                    WorkOrder.assignee == u.username,
                    WorkOrder.status.notin_(["completed", "closed", "cancelled"]),
                )
            )
            load = int(load_result.scalar_one())
            personnel.append({
                "id": u.id,
                "name": u.username,
                "email": u.email,
                "load": load,
            })
        return personnel

    async def _do_list_faults(
        self, turbine_id: int | None = None, status: str | None = None,
    ) -> list[dict]:
        """List faults, optionally filtered by turbine_id or status."""
        q = select(Fault).order_by(Fault.detected_at.desc())
        if turbine_id is not None:
            q = q.where(Fault.turbine_id == turbine_id)
        if status:
            q = q.where(Fault.status == status)
        result = await self.db.execute(q)
        faults = result.scalars().all()
        return [
            {
                "fault_id": f.id,
                "turbine_id": f.turbine_id,
                "fault_type": f.fault_type,
                "confidence": f.confidence,
                "status": f.status,
                "detected_at": f.detected_at.isoformat() if f.detected_at else "",
            }
            for f in faults
        ]

    async def _do_list_turbines(self, status: str | None = None) -> list[dict]:
        """List all turbines, optionally filtered by status."""
        q = select(Turbine).order_by(Turbine.name.asc())
        if status:
            q = q.where(Turbine.status == status)
        result = await self.db.execute(q)
        turbines = result.scalars().all()
        return [
            {
                "turbine_id": t.id,
                "turbine_name": t.name,
                "status": t.status,
                "hi_value": t.hi_value,
                "region": t.region or "",
                "model": t.model or "",
            }
            for t in turbines
        ]

    async def _do_navigate(self, page: str, turbine_id: int | None = None, wo_id: int | None = None) -> dict:
        """Return navigation target for frontend to execute.

        Supported pages: dashboard, diagnosis, prediction, workorders, knowledge, settings, turbine
        If turbine_id with page='turbine', URL is /turbine/{id}
        If wo_id with page='workorders', URL is /workorder?preview={id}
        """
        page = page.lower().strip()
        if page in PAGE_ROUTES:
            url = PAGE_ROUTES[page]
            if page == "turbine" and turbine_id:
                url = f"{url}/{turbine_id}"
            if page == "workorders" and wo_id:
                url = f"{url}?preview={wo_id}"
            return {"navigate_to": url, "page": page, "turbine_id": turbine_id, "wo_id": wo_id}
        raise StepExecutionError(0, "navigate", f"未知页面 '{page}'。支持: {list(PAGE_ROUTES.keys())}")
