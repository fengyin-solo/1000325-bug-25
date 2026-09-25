"""电量结算业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "settlement"
REQUIRED_FIELDS = ["结算单号", "结算对象", "结算周期"]
STATUS_ORDER = ["待核对", "核对中", "已确认", "已付清", "有争议"]
FINAL_STATUS = "已付清"
# 动作 -> (允许发起的当前状态, 目标状态)；已付清是终态，任何动作都进不来
ACTION_RULES = {
    "发起核对": ({"待核对"}, "核对中"),
    "确认结算": ({"核对中", "已确认"}, "已付清"),
    "标记争议": ({"待核对", "核对中", "已确认"}, "有争议"),
    "恢复核对": ({"有争议"}, "核对中"),
}
NEGATIVE_ACTIONS = ["标记争议"]


class SettlementService:
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
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 金额与电量字段给默认口径，保证列表、详情、导出看到的字段一致；
        # 电价标准只透传登记值，不在服务里重算，老口径照旧。
        entry["上网电量"] = values.get("上网电量", 0)
        entry["电价标准"] = values.get("电价标准", "")
        entry["应结金额"] = values.get("应结金额", 0)
        entry["已付金额"] = values.get("已付金额", 0)
        entry["status"] = STATUS_ORDER[0]
        entry["结算状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于电量结算可执行范围"
        current = str(entry.get("status") or "")
        if current == FINAL_STATUS:
            return None, f"结算单 {entry_id} 已付清，核对结果已归档，不能再改动"
        allowed_from, target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if current not in allowed_from:
            return None, f"结算单当前为「{current}」，不能{action}"
        entry["status"] = target
        entry["结算状态"] = target
        entry["pending"] = target != FINAL_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target == FINAL_STATUS:
            # 付清即按应结金额足额到账，列表、详情、导出同一口径
            entry["已付金额"] = entry.get("应结金额", entry.get("已付金额", 0))
        return entry, f"结算单已{action}"
