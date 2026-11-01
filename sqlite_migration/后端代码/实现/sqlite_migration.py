"""sqlite_migration：按声明顺序执行各叶子模块自有的 SQLite 迁移。

规则：specs/2026-11-01-writing-harness-mcp.spec.md 要求 R1、R14。
业务字段：specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节。

迁移声明：`<migrations_root>/<模块名>/<顺序号>_<名字>.sql`，文件头用
`-- tables: a, b` 声明本文件创建的表。执行顺序 = 模块名升序 + 顺序号升序。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SUFFIX = ".sql"
VERSION_TABLE, REQUEST_TABLE = "schema_migrations", "migration_requests"
BOOKKEEPING = (VERSION_TABLE, REQUEST_TABLE)

SCOPE = "PROJECT_SCOPE_VIOLATION"
CONFLICT = "CONFLICT"
ORDER = "MIGRATION_ORDER_CONFLICT"
FAILED = "MIGRATION_FAILED"
NO_ROOT = "MIGRATIONS_ROOT_MISSING"
NO_MODULE = "MIGRATION_MODULE_MISSING"
INVALID = "INVALID_PAYLOAD"

FILE = re.compile(r"^(?P<seq>[0-9]+)_(?P<slug>[^/\\]+)\.sql$")
TABLES = re.compile(r"^--\s*tables\s*:\s*(?P<list>.*)$", re.M)


class SqliteMigrationError(Exception):
    """sqlite_migration 的唯一异常类；code 是稳定错误码。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def migrate(request: dict) -> dict:
    """按声明的顺序应用未执行的迁移；重复执行幂等，冲突与失败一律拒绝。"""
    database = _scope_path(request["database_path"], "database_path")
    root = _scope_path(request["migrations_root"], "migrations_root")
    actor_id = request["actor"]["actor_id"]
    key = request["idempotency_key"]

    connection = _connect(database)
    try:
        _ensure_bookkeeping(connection)
        replay = _replay(connection, actor_id, key, _fingerprint(request))
        if replay is not None:
            return replay

        plan = _plan(root)
        applied = _applied(connection)
        _guard_order(plan, applied)
        _apply(connection, plan, applied)
        _verify_tables(connection, plan)
        result = _result(connection)
        _remember(connection, actor_id, key, _fingerprint(request), result)
        return result
    except sqlite3.Error as exc:
        raise SqliteMigrationError(
            FAILED, "迁移执行失败", {"reason": str(exc)}) from exc
    finally:
        connection.close()


# ---------- 路径与连接 ----------

def _scope_path(raw: str, field: str) -> Path:
    """数据库与迁移根都必须是真实绝对路径；相对路径和目录穿越一律拒绝。"""
    text = str(raw).strip()
    if not os.path.isabs(text) or ".." in Path(text).parts:
        raise SqliteMigrationError(
            SCOPE, "路径必须是绝对路径且不含目录穿越", {"field": field, "path": text})
    return Path(os.path.realpath(text))


def _connect(database: Path) -> sqlite3.Connection:
    """打开库文件：WAL、外键、出错即回滚到语句前。"""
    try:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(database), isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
    except (OSError, sqlite3.Error) as exc:
        raise SqliteMigrationError(
            FAILED, "数据库打不开", {"database_path": str(database),
                                     "reason": str(exc)}) from exc
    return connection


# ---------- 台账 ----------

def _ensure_bookkeeping(connection: sqlite3.Connection) -> None:
    """模块自己的两本台账：已执行迁移、幂等请求。"""
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} ("
        " version INTEGER PRIMARY KEY, module TEXT NOT NULL, seq INTEGER NOT NULL,"
        " name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {REQUEST_TABLE} ("
        " actor_id TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL,"
        " result TEXT NOT NULL, recorded_at TEXT NOT NULL,"
        " PRIMARY KEY (actor_id, key))")


def _applied(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        f"SELECT version, module, seq, name, checksum FROM {VERSION_TABLE}"
        " ORDER BY version").fetchall()
    return [{"version": row[0], "module": row[1], "seq": row[2],
             "name": row[3], "checksum": row[4]} for row in rows]


def _replay(connection: sqlite3.Connection, actor_id: str, key: str,
            fingerprint: str):
    """同 actor、同 key、同请求返回首次结果；同 key 异请求判复用错误。"""
    row = connection.execute(
        f"SELECT request_hash, result FROM {REQUEST_TABLE}"
        " WHERE actor_id = ? AND key = ?", (actor_id, key)).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        raise SqliteMigrationError(
            "IDEMPOTENCY_KEY_REUSE", "同一幂等键被不同请求复用",
            {"idempotency_key": key, "actor_id": actor_id})
    return json.loads(row[1])


def _remember(connection: sqlite3.Connection, actor_id: str, key: str,
              fingerprint: str, result: dict) -> None:
    connection.execute(
        f"INSERT INTO {REQUEST_TABLE}"
        " (actor_id, key, request_hash, result, recorded_at) VALUES (?, ?, ?, ?, ?)",
        (actor_id, key, fingerprint, json.dumps(result, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()))


def _result(connection: sqlite3.Connection) -> dict:
    versions = [row[0] for row in connection.execute(
        f"SELECT version FROM {VERSION_TABLE} ORDER BY version")]
    return {"applied_versions": versions,
            "current_version": versions[-1] if versions else 0}


# ---------- 迁移声明与执行 ----------

def _plan(root: Path) -> list[dict]:
    """读迁移根，按模块名升序 + 顺序号升序排出执行计划。"""
    if not root.is_dir():
        raise SqliteMigrationError(
            NO_ROOT, "迁移根不存在", {"migrations_root": str(root)})
    plan: list[dict] = []
    for module_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(p for p in module_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == SUFFIX)
        if not files:
            raise SqliteMigrationError(
                NO_MODULE, "迁移模块目录里没有迁移文件",
                {"module": module_dir.name, "module_dir": str(module_dir)})
        seqs = []
        for path in files:
            match = FILE.match(path.name)
            if match is None:
                raise SqliteMigrationError(
                    FAILED, "迁移文件名不合 `<顺序号>_<名字>.sql`",
                    {"path": str(path)})
            if not _within(root, path):
                raise SqliteMigrationError(
                    SCOPE, "迁移文件指到迁移根之外", {"path": str(path)})
            text = path.read_text(encoding="utf-8")
            seqs.append(int(match.group("seq")))
            plan.append({
                "module": module_dir.name,
                "seq": int(match.group("seq")),
                "name": match.group("slug"),
                "path": path,
                "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
                "tables": _declared(text, path),
            })
        if seqs != list(range(1, len(seqs) + 1)):
            raise SqliteMigrationError(
                ORDER, "同一模块的顺序号必须从 1 起连续",
                {"module": module_dir.name, "seqs": seqs})
    return plan


def _within(root: Path, path: Path) -> bool:
    return Path(os.path.realpath(path)).is_relative_to(root)


def _declared(text: str, path: Path) -> list[str]:
    """读文件头的 `-- tables: a, b` 声明；没有声明就一个表都不许建。"""
    match = TABLES.search(text)
    if match is None:
        return []
    names = [item.strip() for item in match.group("list").split(",")]
    names = [name for name in names if name]
    if not names:
        raise SqliteMigrationError(
            FAILED, "`-- tables:` 声明为空", {"path": str(path)})
    return names


def _guard_order(plan: list[dict], applied: list[dict]) -> None:
    """已执行顺序必须是声明顺序的前缀，且文件内容不得改动。"""
    if len(applied) > len(plan):
        raise SqliteMigrationError(
            ORDER, "已执行的迁移在声明里找不到",
            {"applied": len(applied), "declared": len(plan)})
    for index, row in enumerate(applied):
        entry = plan[index]
        if (row["module"], row["seq"], row["name"]) != \
                (entry["module"], entry["seq"], entry["name"]):
            raise SqliteMigrationError(
                ORDER, "新迁移插到了已执行迁移之前",
                {"version": row["version"], "applied": row["name"],
                 "declared": entry["name"]})
        if row["checksum"] != entry["checksum"]:
            raise SqliteMigrationError(
                CONFLICT, "已执行的迁移文件内容被改动",
                {"module": row["module"], "name": row["name"]})


def _apply(connection: sqlite3.Connection, plan: list[dict],
           applied: list[dict]) -> None:
    """逐个迁移各开一个事务；任一失败即回滚该迁移并保留已执行的。"""
    for index in range(len(applied), len(plan)):
        entry, version = plan[index], index + 1
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in _statements(entry["text"]):
                connection.execute(statement)
            connection.execute(
                f"INSERT INTO {VERSION_TABLE}"
                " (version, module, seq, name, checksum, applied_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (version, entry["module"], entry["seq"], entry["name"],
                 entry["checksum"], datetime.now(timezone.utc).isoformat()))
            connection.execute("COMMIT")
        except sqlite3.Error as exc:
            connection.execute("ROLLBACK")
            raise SqliteMigrationError(
                FAILED, "迁移语句执行失败",
                {"module": entry["module"], "name": entry["name"],
                 "reason": str(exc)}) from exc


def _statements(text: str) -> list[str]:
    """按完整语句切分：字符串与注释里的分号不算语句边界。

    逐字符累积，`complete_statement` 为真即切出一条——这样同一行写两条
    语句也能分开，而不是把整行当成一条。
    """
    statements: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            if buffer.strip() != ";":
                statements.append(buffer)
            buffer = ""
    leftover = [l.strip() for l in buffer.splitlines()
                if l.strip() and not l.strip().startswith("--")]
    if leftover:  # 末尾只剩空白与整行注释时不算残留语句
        raise SqliteMigrationError(
            FAILED, "迁移文件末尾有不完整语句", {"tail": leftover[0][:80]})
    return statements


def _verify_tables(connection: sqlite3.Connection, plan: list[dict]) -> None:
    """迁移只许创建自己声明的表；多建一张即判失败。"""
    declared = set(BOOKKEEPING)
    for entry in plan:
        declared.update(entry["tables"])
    actual = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%'")}
    extra = sorted(actual - declared)
    if extra:
        raise SqliteMigrationError(
            FAILED, "迁移建了未声明的表", {"undeclared_tables": extra})


def _fingerprint(request: dict) -> str:
    """请求指纹：只取影响迁移结果的字段，供幂等重放比对。"""
    material = {"project_id": request.get("project_id", ""),
                "database_path": str(request["database_path"]).strip(),
                "migrations_root": str(request["migrations_root"]).strip()}
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
