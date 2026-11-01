"""sqlite_migration 的命令薄壳：校验入参 → 调实现 → 返回统一 envelope。

入口：run(payload: dict) -> dict
contract：specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节
"""

from __future__ import annotations

import os

from 实现.sqlite_migration import INVALID, SqliteMigrationError, migrate


def run(payload: dict) -> dict:
    """薄壳只做三件事：校验入参、分发到实现、封装返回。"""
    try:
        _validate(payload)
        data = migrate(payload)
        return {"ok": True, "data": data, "error": None}
    except SqliteMigrationError as exc:
        return {"ok": False, "data": None,
                "error": {"code": exc.code, "message": exc.message,
                          "details": exc.details}}
    except Exception as exc:  # noqa: BLE001 —— 薄壳兜住未预期异常，仍返回 envelope
        return {"ok": False, "data": None,
                "error": {"code": INVALID, "message": "请求无法处理",
                          "details": {"reason": str(exc)}}}


def _validate(payload: dict) -> None:
    """校验 envelope 与业务字段；所有键名以接口总表为准。"""
    if not isinstance(payload, dict):
        raise SqliteMigrationError(INVALID, "payload 必须是 dict", {})
    missing = [key for key in ("request_id", "project_id", "actor",
                              "idempotency_key", "database_path",
                              "migrations_root") if key not in payload]
    if missing:
        raise SqliteMigrationError(INVALID, "缺必填入参", {"missing": missing})
    actor = payload["actor"]
    if not isinstance(actor, dict) or not str(actor.get("actor_id", "")).strip():
        raise SqliteMigrationError(INVALID, "actor 必须带 actor_id", {})
    if not str(payload["request_id"]).strip():
        raise SqliteMigrationError(INVALID, "request_id 不能为空", {})
    if not isinstance(payload["project_id"], str):
        raise SqliteMigrationError(INVALID, "project_id 必须是 str", {})
    if not str(payload["idempotency_key"]).strip():
        raise SqliteMigrationError(INVALID, "写操作必须带 idempotency_key", {})
    for field in ("database_path", "migrations_root"):
        raw = payload[field]
        if not isinstance(raw, str) or not raw.strip():
            raise SqliteMigrationError(
                INVALID, "路径字段不能为空", {"field": field})
        if not os.path.isabs(raw.strip()):
            raise SqliteMigrationError(
                INVALID, "路径字段必须是绝对路径", {"field": field, "path": raw})
