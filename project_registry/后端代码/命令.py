"""project_registry 的命令薄壳：校验入参 → 调实现 → 返回统一 envelope。

入口：run(payload: dict) -> dict
contract：specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节
"""

from __future__ import annotations

from 实现.project_registry import (CONFLICT, INVALID, ProjectRegistryError,
                                  open_project, register, resolve)

ACTIONS = ("register", "open", "resolve")
REQUIRED = ("request_id", "project_id", "actor", "idempotency_key", "action")
ROOT_ACTION_NAMES = {"register": ("name",)}


def run(payload: dict) -> dict:
    """薄壳只做三件事：校验入参、分发到实现、封装返回。"""
    try:
        _validate(payload)
        data = _dispatch(payload)
        return {"ok": True, "data": data, "error": None}
    except ProjectRegistryError as exc:
        return {"ok": False, "data": None, **{"error": _error(exc)}}
    except Exception as exc:  # noqa: BLE001 —— 薄壳兜住未预期异常，仍返回 envelope
        return {"ok": False, "data": None,
                "error": {"code": INVALID, "message": "请求无法处理",
                          "details": {"reason": str(exc)}}}


def _error(exc: ProjectRegistryError) -> dict:
    return {"code": exc.code, "message": exc.message, "details": exc.details}


def _validate(payload: dict) -> None:
    """校验 envelope 与业务字段；所有键名以接口总表为准。"""
    if not isinstance(payload, dict):
        raise ProjectRegistryError(INVALID, "payload 必须是 dict", {})
    missing = [key for key in REQUIRED if key not in payload]
    if missing:
        raise ProjectRegistryError(
            INVALID, "缺必填入参", {"missing": missing})
    action = payload["action"]
    if action not in ACTIONS:
        raise ProjectRegistryError(
            INVALID, "未知 action", {"action": action, "allowed": list(ACTIONS)})
    actor = payload["actor"]
    if not isinstance(actor, dict) or not str(actor.get("actor_id", "")).strip():
        raise ProjectRegistryError(
            INVALID, "actor 必须带 actor_id", {"actor": actor})
    if not str(payload["idempotency_key"]).strip():
        raise ProjectRegistryError(INVALID, "写操作必须带 idempotency_key", {})
    if not isinstance(payload["request_id"], str) or not payload["request_id"].strip():
        raise ProjectRegistryError(INVALID, "request_id 不能为空", {})
    if not isinstance(payload["project_id"], str):
        raise ProjectRegistryError(INVALID, "project_id 必须是 str", {})
    raw_root = payload.get("root_path")
    if not isinstance(raw_root, str) or not raw_root.strip():
        raise ProjectRegistryError(INVALID, "root_path 不能为空", {})
    for key in ROOT_ACTION_NAMES.get(action, ()):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProjectRegistryError(
                INVALID, "缺必填业务字段", {"field": key})


def _dispatch(payload: dict) -> dict:
    action = payload["action"]
    if action == "register":
        return register(payload)
    if action == "open":
        return open_project(payload)
    return resolve(payload)


__all__ = ["run", "ProjectRegistryError", "ACTIONS", "CONFLICT"]
