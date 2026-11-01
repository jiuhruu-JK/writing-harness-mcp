"""sqlite_migration 的命令薄壳：校验入参 → 调实现 → 返回统一 envelope。

入口：run(payload: dict) -> dict
contract：specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REQUIRED = ("request_id", "project_id", "actor", "idempotency_key",
            "database_path", "migrations_root")
_IMPL_ALIAS = "writing_harness_sqlite_migration_impl"


def _load_impl():
    """按唯一别名加载本模块的实现。

    每个模块的入口都叫 `命令.py`、实现包都叫 `实现/`；把它们当顶层包
    导入会让同进程内的模块互相顶替。这里按文件路径加载、用唯一模块名，
    多个模块同进程共存不冲突。
    """
    existing = sys.modules.get(_IMPL_ALIAS)
    if existing is not None:
        return existing
    source = Path(__file__).resolve().parent / "实现" / "sqlite_migration.py"
    spec = importlib.util.spec_from_file_location(_IMPL_ALIAS, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[_IMPL_ALIAS] = module
    spec.loader.exec_module(module)
    return module


_IMPL = _load_impl()
SqliteMigrationError = _IMPL.SqliteMigrationError
INVALID = _IMPL.INVALID


def run(payload: dict) -> dict:
    """薄壳只做三件事：校验入参、分发到实现、封装返回。"""
    try:
        _validate(payload)
        data = _IMPL.migrate(payload)
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
    missing = [key for key in REQUIRED if key not in payload]
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
