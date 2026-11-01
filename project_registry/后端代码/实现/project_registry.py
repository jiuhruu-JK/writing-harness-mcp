"""project_registry：登记并打开单一项目数据根，强制项目作用域。

规则：specs/2026-11-01-writing-harness-mcp.spec.md 要求 R1。
业务字段：specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
REGISTRY_DIR = ".writing-harness"
DB_FILE = "registry.db"

COLUMNS = "project_id, name, root_path, schema_version, registered_at"
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY,"
    " name TEXT NOT NULL, root_path TEXT NOT NULL UNIQUE,"
    " schema_version INTEGER NOT NULL, registered_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS idempotency (actor_id TEXT NOT NULL,"
    " key TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL,"
    " PRIMARY KEY (actor_id, key))")

SCOPE = "PROJECT_SCOPE_VIOLATION"
CONFLICT = "CONFLICT"
REUSE = "IDEMPOTENCY_KEY_REUSE"
NOT_REGISTERED = "PROJECT_NOT_REGISTERED"
CORRUPT = "PROJECT_REGISTRY_CORRUPT"
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
    scope = request.get("project_id") or ""
    _guard_nested_root(root)
    conn = _connect(root)
    try:
        _ensure_schema(conn)
        return _register_in_txn(conn, root, name, scope, request)
    except ProjectRegistryError:
        _safe_rollback(conn)
        raise
    except sqlite3.Error as exc:
        _safe_rollback(conn)
        code = CONFLICT if isinstance(exc, sqlite3.IntegrityError) else STORE_IO
        raise ProjectRegistryError(
            code, "登记事务失败",
            {"root_path": str(root), "reason": str(exc)}) from exc
    finally:
        conn.close()


def _register_in_txn(conn: sqlite3.Connection, root: Path, name: str,
                     scope: str, request: dict) -> dict:
    """幂等校验与登记约束在同一个 SQLite 事务内完成。"""
    actor_id = request["actor"]["actor_id"]
    key = request["idempotency_key"]
    fingerprint = _fingerprint(request)
    conn.execute("BEGIN IMMEDIATE")
    cached = _replay(conn, actor_id, key, fingerprint)
    if cached is not None:
        conn.execute("COMMIT")
        return cached
    row = _row_by_root(conn, root)
    if row is not None:
        if scope and scope != row["project_id"]:
            raise ProjectRegistryError(
                SCOPE, "请求的项目作用域与登记身份不一致",
                {"project_id": scope, "registered_project_id": row["project_id"]})
        if row["name"] != name:
            raise ProjectRegistryError(
                CONFLICT, "同一数据根已登记为另一个项目",
                {"root_path": str(root), "registered_name": row["name"],
                 "name": name})
        conn.execute("COMMIT")
        return _data(row)
    if scope:
        raise ProjectRegistryError(
            SCOPE, "登记新项目时不得声明既有项目身份", {"project_id": scope})
    record = {"project_id": uuid.uuid4().hex, "name": name,
              "root_path": str(root), "schema_version": SCHEMA_VERSION,
              "registered_at": datetime.now(timezone.utc).isoformat()}
    conn.execute(
        "INSERT INTO projects (project_id, name, root_path, schema_version,"
        " registered_at) VALUES (?, ?, ?, ?, ?)",
        (record["project_id"], record["name"], record["root_path"],
         record["schema_version"], record["registered_at"]))
    data = _data(record)
    _remember(conn, actor_id, key, fingerprint, data)
    conn.execute("COMMIT")
    return data


def open_project(request: dict) -> dict:
    """打开已登记的数据根；必须带本项目身份，其他身份一律判作用域越权。"""
    return _read_guarded(lambda root, row: _data(row), request)


def resolve(request: dict) -> dict:
    """校验根内相对路径不越出数据根；越界一律拒绝（R1 路径逃逸）。"""
    return _read_guarded(
        lambda root, row: (_resolve_within(root, request.get("name") or ""),
                           _data(row))[1], request)


def _read_guarded(action, request: dict) -> dict:
    """读路径统一骨架：规范根 → 打开既有库 → 校验作用域 → 交给 action。"""
    root = _scope_root(request["root_path"])
    conn = _connect_read(root)
    try:
        row = _require_row(conn, root)
        _guard_scope(request.get("project_id") or "", row)
        return action(root, row)
    except sqlite3.Error as exc:
        raise ProjectRegistryError(
            STORE_IO, "登记档案读不了",
            {"root_path": str(root), "reason": str(exc)}) from exc
    finally:
        conn.close()


def _guard_scope(scope: str, row: dict) -> None:
    """读取必须带本项目作用域；缺作用域或身份不符一律拒绝。"""
    if not scope:
        raise ProjectRegistryError(
            SCOPE, "读取项目记录必须带项目作用域",
            {"registered_project_id": row["project_id"]})
    if scope != row["project_id"]:
        raise ProjectRegistryError(
            SCOPE, "请求的项目作用域与登记身份不一致",
            {"project_id": scope, "registered_project_id": row["project_id"]})


def _guard_nested_root(root: Path) -> None:
    """已登记项目根内的目录不能再登记为第二个项目。"""
    for parent in root.parents:
        if _db_path(parent).exists():
            raise ProjectRegistryError(
                CONFLICT, "已登记项目根内的目录不能成为第二个项目",
                {"root_path": str(root), "registered_root": str(parent)})


def _scope_root(raw: str) -> Path:
    """把入参数据根规范成真实绝对路径；相对路径与目录穿越一律拒绝。"""
    text = str(raw).strip()
    if not os.path.isabs(text) or ".." in Path(text).parts:
        raise ProjectRegistryError(
            SCOPE, "数据根必须是根内绝对路径", {"root_path": text})
    return Path(os.path.realpath(text))


def _resolve_within(root: Path, raw: str) -> Path:
    """解析根内相对路径；绝对路径、目录穿越、根外符号链接、内部登记目录一律拒绝。"""
    text = str(raw).strip()
    if not text:
        raise ProjectRegistryError(
            INVALID, "入参 `name` 不能为空", {"field": "name"})
    if os.path.isabs(text) or ".." in Path(text).parts:
        raise ProjectRegistryError(
            SCOPE, "项目内路径不得为绝对路径或含目录穿越", {"name": text})
    if Path(os.path.normpath(text)).parts[0] == REGISTRY_DIR:
        raise ProjectRegistryError(
            SCOPE, "项目内路径不得指向模块自有登记目录", {"name": text})
    candidate = Path(os.path.normpath(os.path.join(str(root), text)))
    real = Path(os.path.realpath(candidate))
    if not candidate.is_relative_to(root) or not real.is_relative_to(root):
        raise ProjectRegistryError(
            SCOPE, "路径指到项目数据根之外",
            {"name": text, "resolved_path": str(real), "data_root": str(root)})
    return real


def _db_path(root: Path) -> Path:
    return root / REGISTRY_DIR / DB_FILE


def _connect(root: Path) -> sqlite3.Connection:
    """打开（必要时创建）登记库；写路径用它。"""
    try:
        path = _db_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except (OSError, sqlite3.Error) as exc:
        raise ProjectRegistryError(
            STORE_IO, "登记库打不开",
            {"root_path": str(root), "reason": str(exc)}) from exc


def _connect_read(root: Path) -> sqlite3.Connection:
    """打开既有登记库；根未登记即报错，读路径用它。"""
    path = _db_path(root)
    if not path.exists():
        raise ProjectRegistryError(
            NOT_REGISTERED, "数据根尚未登记项目", {"root_path": str(root)})
    try:
        return sqlite3.connect(str(path), isolation_level=None)
    except sqlite3.Error as exc:
        raise ProjectRegistryError(
            STORE_IO, "登记库打不开",
            {"root_path": str(root), "reason": str(exc)}) from exc


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """本模块自己的两张表：项目登记与幂等请求。"""
    try:
        for statement in SCHEMA:
            conn.execute(statement)
    except sqlite3.Error as exc:
        raise ProjectRegistryError(
            CORRUPT, "登记库建表失败", {"reason": str(exc)}) from exc


def _row_by_root(conn: sqlite3.Connection, root: Path) -> dict | None:
    row = conn.execute(f"SELECT {COLUMNS} FROM projects WHERE root_path = ?",
                       (str(root),)).fetchone()
    return None if row is None else _as_dict(row)


def _require_row(conn: sqlite3.Connection, root: Path) -> dict:
    row = _row_by_root(conn, root)
    if row is None:
        raise ProjectRegistryError(
            NOT_REGISTERED, "数据根尚未登记项目", {"root_path": str(root)})
    return row


def _as_dict(row: tuple) -> dict:
    keys = ("project_id", "name", "root_path", "schema_version", "registered_at")
    return dict(zip(keys, row))


def _replay(conn: sqlite3.Connection, actor_id: str, key: str,
            fingerprint: str) -> dict | None:
    """同 actor、同 key、同请求返回首次结果；同 key 异请求判复用错误。"""
    row = conn.execute("SELECT request_hash, result FROM idempotency"
                       " WHERE actor_id = ? AND key = ?", (actor_id, key)).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        raise ProjectRegistryError(
            REUSE, "同一幂等键被不同请求复用",
            {"idempotency_key": key, "actor_id": actor_id})
    return json.loads(row[1])


def _remember(conn: sqlite3.Connection, actor_id: str, key: str,
              fingerprint: str, data: dict) -> None:
    conn.execute("INSERT INTO idempotency (actor_id, key, request_hash, result)"
                 " VALUES (?, ?, ?, ?)",
                 (actor_id, key, fingerprint, json.dumps(data, ensure_ascii=False)))


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _fingerprint(request: dict) -> str:
    """请求指纹：只取影响登记结果的字段，供幂等重放比对。"""
    material = {"action": request["action"],
                "root_path": str(request["root_path"]).strip(),
                "name": request.get("name", "")}
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _data(record: dict) -> dict:
    """接口总表规定返回三键：project_id、schema_version、data_root。"""
    root = Path(record["root_path"])
    return {"project_id": record["project_id"],
            "schema_version": record["schema_version"],
            "data_root": {"root_path": record["root_path"],
                          "state_db_path": str(_db_path(root)),
                          "status": "registered",
                          "name": record["name"],
                          "registered_at": record["registered_at"]}}
