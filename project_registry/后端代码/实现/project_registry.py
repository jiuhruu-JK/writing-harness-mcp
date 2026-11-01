"""project_registry：登记并打开单一项目数据根，强制项目作用域。

规则：specs/2026-11-01-writing-harness-mcp.spec.md 要求 R1。
业务字段：specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
REGISTRY_DIR = ".writing-harness"
MARKER_FILE = "project.json"
JOURNAL_FILE = "idempotency.json"

SCOPE = "PROJECT_SCOPE_VIOLATION"
CONFLICT = "CONFLICT"
REUSE = "IDEMPOTENCY_KEY_REUSE"
NOT_REGISTERED = "PROJECT_NOT_REGISTERED"
CORRUPT = "PROJECT_MARKER_CORRUPT"
STORE_IO = "PROJECT_STORE_IO_ERROR"
INVALID = "INVALID_PAYLOAD"


class ProjectRegistryError(Exception):
    """project_registry 的唯一异常类；code 是稳定错误码。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def register(request: dict) -> dict:
    """登记数据根；同根同名再登记返回既有身份，同根异名判冲突。"""
    root = _scope_root(request["root_path"])
    name = request["name"]
    actor_id = request["actor"]["actor_id"]
    key = request["idempotency_key"]

    replay = _replay(root, actor_id, key, _fingerprint(request))
    if replay is not None:
        return replay
    record = _read_marker(root)
    if record is not None:
        if record["name"] != name:
            raise ProjectRegistryError(
                CONFLICT, "同一数据根已登记为另一个项目",
                {"root_path": str(root), "registered_name": record["name"],
                 "name": name})
        return _project_data(root, record)

    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    record = {
        "project_id": uuid.uuid4().hex,
        "name": name,
        "root_path": str(root),
        "schema_version": SCHEMA_VERSION,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(_marker_path(root), record)
    data = _project_data(root, record)
    _remember(root, actor_id, key, _fingerprint(request), data)
    return data


def open_project(request: dict) -> dict:
    """打开已登记的数据根；带其他项目身份一律判作用域越权。"""
    root = _scope_root(request["root_path"])
    record = _require_marker(root)
    _guard_scope(request["project_id"], record)
    return _project_data(root, record)


def resolve(request: dict) -> dict:
    """把相对项目根的路径解析成真实路径；越出根范围一律拒绝（R1 路径逃逸）。"""
    root = _scope_root(request["root_path"])
    record = _require_marker(root)
    scope = request["project_id"]
    if not scope:
        raise ProjectRegistryError(
            SCOPE, "读取项目内路径必须带项目作用域", {"root_path": str(root)})
    _guard_scope(scope, record)
    target = _resolve_within(root, request["name"])
    data = _project_data(root, record)
    data["resolved_path"] = str(target)
    return data


def _guard_scope(scope: str, record: dict) -> None:
    """空作用域视为首次打开；填了作用域就必须与本项目身份一致。"""
    if scope and scope != record["project_id"]:
        raise ProjectRegistryError(
            SCOPE, "请求的项目作用域与登记身份不一致",
            {"project_id": scope, "registered_project_id": record["project_id"]})


def _scope_root(raw: str) -> Path:
    """把入参数据根规范成真实绝对路径；相对路径与目录穿越一律拒绝。"""
    text = raw.strip()
    if not os.path.isabs(text) or ".." in Path(text).parts:
        raise ProjectRegistryError(
            SCOPE, "数据根必须是根内绝对路径", {"root_path": text})
    return Path(os.path.realpath(text))


def _resolve_within(root: Path, raw: str) -> Path:
    """解析根内相对路径；绝对路径、目录穿越、根外符号链接一律拒绝。"""
    text = raw.strip()
    if not text:
        raise ProjectRegistryError(
            INVALID, "入参 `name` 不能为空", {"field": "name"})
    if os.path.isabs(text) or ".." in Path(text).parts:
        raise ProjectRegistryError(
            SCOPE, "项目内路径不得为绝对路径或含目录穿越", {"name": text})
    candidate = Path(os.path.normpath(os.path.join(str(root), text)))
    real = Path(os.path.realpath(candidate))
    if not candidate.is_relative_to(root) or not real.is_relative_to(root):
        raise ProjectRegistryError(
            SCOPE, "路径指到项目数据根之外",
            {"name": text, "resolved_path": str(real), "data_root": str(root)})
    return real


def _marker_path(root: Path) -> Path:
    return root / REGISTRY_DIR / MARKER_FILE


def _journal_path(root: Path) -> Path:
    return root / REGISTRY_DIR / JOURNAL_FILE


def _read_json(path: Path, label: str) -> object | None:
    """读 JSON 档案；不存在返回 None，读不了或解析不了即报错。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProjectRegistryError(
            STORE_IO, f"{label}读不了", {"path": str(path), "reason": str(exc)}) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectRegistryError(
            CORRUPT, f"{label}无法解析", {"path": str(path), "reason": str(exc)}) from exc


def _read_marker(root: Path) -> dict | None:
    path = _marker_path(root)
    record = _read_json(path, "登记档案")
    if record is None:
        return None
    if not isinstance(record, dict) or not isinstance(record.get("project_id"), str) \
            or not isinstance(record.get("name"), str):
        raise ProjectRegistryError(
            CORRUPT, "登记档案缺 project_id 或 name", {"path": str(path)})
    return record


def _require_marker(root: Path) -> dict:
    record = _read_marker(root)
    if record is None:
        raise ProjectRegistryError(
            NOT_REGISTERED, "数据根尚未登记项目", {"root_path": str(root)})
    return record


def _read_journal(root: Path) -> list:
    records = _read_json(_journal_path(root), "幂等台账")
    if records is None:
        return []
    if not isinstance(records, list):
        raise ProjectRegistryError(
            CORRUPT, "幂等台账不是记录列表", {"path": str(_journal_path(root))})
    return records


def _replay(root: Path, actor_id: str, key: str, fingerprint: str) -> dict | None:
    """同 actor、同 key、同请求返回首次结果；同 key 异请求判复用错误。"""
    for record in _read_journal(root):
        if record.get("actor_id") != actor_id or record.get("key") != key:
            continue
        if record.get("request_hash") == fingerprint:
            return record.get("data")
        raise ProjectRegistryError(
            REUSE, "同一幂等键被不同请求复用",
            {"idempotency_key": key, "actor_id": actor_id})
    return None


def _remember(root: Path, actor_id: str, key: str, fingerprint: str,
              data: dict) -> None:
    records = _read_journal(root)
    records.append({"actor_id": actor_id, "key": key,
                    "request_hash": fingerprint, "data": data})
    _write_json(_journal_path(root), records)


def _fingerprint(request: dict) -> str:
    """请求指纹：只取影响登记结果的字段，供幂等重放比对。"""
    material = {"action": request["action"],
                "root_path": request["root_path"].strip(),
                "name": request.get("name", "")}
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    """先写临时文件再原子替换，半途失败不留下半个档案。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            dir=str(path.parent), prefix=".tmp-", suffix=".json",
            delete=False, mode="w", encoding="utf-8")
    except OSError as exc:
        raise ProjectRegistryError(
            STORE_IO, "登记目录不可写", {"path": str(path), "reason": str(exc)}) from exc
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ProjectRegistryError(
            STORE_IO, "登记档案写入失败", {"path": str(path), "reason": str(exc)}) from exc


def _project_data(root: Path, record: dict) -> dict:
    return {
        "project_id": record["project_id"],
        "schema_version": record.get("schema_version", SCHEMA_VERSION),
        "data_root": {
            "root_path": str(root),
            "marker_path": str(_marker_path(root)),
            "status": "registered",
            "name": record["name"],
            "registered_at": record.get("registered_at", ""),
        },
    }
