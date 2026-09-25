"""电量结算业务规则：状态流转、字段校验与金额口径都收在这里。

口径约定（老电价标准，保持不变）：
    应结金额 = 上网电量 × 电价标准

金额只在一个地方（present）统一产出，列表、明细、导出共用同一份投影，
保证三个入口看到的应结/已付金额始终一致。

状态机（确认结果一旦落定即不可回退）：
    待核对 --发起核对--> 核对中 --确认结算--> 已确认 --登记付清--> 已付清（终态，锁定）
    待核对/核对中/已确认 --标记争议--> 有争议 --解除争议--> 争议前的原状态
已付清为终态：周期、金额、状态全部冻结，不再接受任何动作；
有争议仅挂起核对流程，解除后回到原状态，记录仍留在原结算周期。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "settlement"
REQUIRED_FIELDS = ["结算单号", "结算对象", "结算周期"]
# 登记时允许一并写入的业务字段（金额不在其中，按老口径由电量、电价推导）
OPTIONAL_FIELDS = ["上网电量", "电价标准"]
NUMERIC_FIELDS = ["上网电量", "电价标准", "已付金额"]

STATUS_PENDING = "待核对"
STATUS_CHECKING = "核对中"
STATUS_CONFIRMED = "已确认"
STATUS_SETTLED = "已付清"
STATUS_DISPUTED = "有争议"
STATUS_ORDER = [
    STATUS_PENDING,
    STATUS_CHECKING,
    STATUS_CONFIRMED,
    STATUS_SETTLED,
    STATUS_DISPUTED,
]
# 终态：进入后任何动作都被拒绝，字段与周期一并锁定
TERMINAL_STATUSES = {STATUS_SETTLED}

ACTION_START = "发起核对"
ACTION_CONFIRM = "确认结算"
ACTION_SETTLE = "登记付清"
ACTION_DISPUTE = "标记争议"
ACTION_RESOLVE = "解除争议"

# 每个（当前状态, 动作）允许流转到的目标状态
TRANSITIONS: dict[tuple[str, str], str] = {
    (STATUS_PENDING, ACTION_START): STATUS_CHECKING,
    (STATUS_CHECKING, ACTION_CONFIRM): STATUS_CONFIRMED,
    (STATUS_CONFIRMED, ACTION_SETTLE): STATUS_SETTLED,
    (STATUS_PENDING, ACTION_DISPUTE): STATUS_DISPUTED,
    (STATUS_CHECKING, ACTION_DISPUTE): STATUS_DISPUTED,
    (STATUS_CONFIRMED, ACTION_DISPUTE): STATUS_DISPUTED,
    # 解除争议的目标状态在 run_action 里按争议前状态动态决定
}


def _to_number(value: Any) -> float:
    """把电量、电价、金额统一解析成数值；占位文本等无法解析的内容按 0 处理。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _round_money(value: float) -> float:
    """金额保留两位小数，避免不同入口因浮点尾差显示不一致。"""
    return round(value + 0.0, 2)


class SettlementService:
    # ---- 读取 ----------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [self.present(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self.present(row) if row is not None else None

    def present(self, entry: dict[str, Any]) -> dict[str, Any]:
        """统一对外投影：列表、明细、导出都走这里，金额口径只有这一份。

        - 应结金额：确认后冻结在快照里；未确认时按老口径（电量×电价）现算，
          两者都经过同一处四舍五入。
        - 已付金额：以登记的实付为准；已付清时必然等于应结金额。
        - 结算状态：直接镜像内部 status，杜绝列表与详情各显示各的。
        """
        view = dict(entry)
        current = str(entry.get("status") or "")
        if "应结金额快照" in entry:
            payable = _to_number(entry["应结金额快照"])
        else:
            payable = _to_number(entry.get("上网电量")) * _to_number(entry.get("电价标准"))
        paid = _to_number(entry.get("已付金额"))
        if entry.get("status") == STATUS_SETTLED:
            # 终态锁定：已付即应结，任何历史脏数据在这里都被校正成一致
            paid = payable
        view["应结金额"] = _round_money(payable)
        view["已付金额"] = _round_money(paid)
        view["结算状态"] = entry.get("status")
        view["可执行动作"] = self.available_actions(current)
        return view

    # ---- 写入 ----------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field)).strip()
        for field in OPTIONAL_FIELDS:
            if values.get(field) not in (None, ""):
                entry[field] = values.get(field)
        for field in NUMERIC_FIELDS:
            if field in entry:
                entry[field] = _to_number(entry[field])
        entry["status"] = STATUS_PENDING
        entry["已付金额"] = 0.0
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self.present(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"

        current = str(entry.get("status") or "")
        if current in TERMINAL_STATUSES:
            return None, f"结算单状态为「{current}」，结算周期与金额已锁定，不能再执行「{action}」"

        if action == ACTION_RESOLVE:
            if current != STATUS_DISPUTED:
                return None, f"结算单当前为「{current}」，只有争议中的单据可以解除争议"
            target = str(entry.get("争议前状态") or STATUS_PENDING)
            if target not in STATUS_ORDER or target in TERMINAL_STATUSES:
                target = STATUS_PENDING
        else:
            target = TRANSITIONS.get((current, action))
            if target is None:
                allowed = self.available_actions(current)
                hint = f"，当前可执行：{'、'.join(allowed)}" if allowed else ""
                return None, f"「{current}」状态下不能执行「{action}」{hint}"

        # 确认时冻结应结金额快照，此后电量、电价再怎么变都不影响已确认口径
        if target == STATUS_CONFIRMED and "应结金额快照" not in entry:
            entry["应结金额快照"] = _round_money(
                _to_number(entry.get("上网电量")) * _to_number(entry.get("电价标准"))
            )
        # 进入争议时记住原状态，解除后回到原周期、原核对进度
        if target == STATUS_DISPUTED:
            entry["争议前状态"] = current
        if current == STATUS_DISPUTED and action == ACTION_RESOLVE:
            entry.pop("争议前状态", None)
        # 付清时按应结金额结清，已付与应结永远相等
        if target == STATUS_SETTLED:
            entry["已付金额"] = self.present(entry)["应结金额"]

        entry["status"] = target
        entry["pending"] = target in (STATUS_PENDING, STATUS_CHECKING)
        entry["abnormal"] = target == STATUS_DISPUTED
        return self.present(entry), f"结算单已{action}"

    def available_actions(self, status: str) -> list[str]:
        """给前端用的动作清单：终态不给任何动作，争议态只给解除争议。"""
        if status in TERMINAL_STATUSES:
            return []
        if status == STATUS_DISPUTED:
            return [ACTION_RESOLVE]
        return [action for (state, action) in TRANSITIONS if state == status]
