"""sqlite_migration：按声明顺序执行各叶子模块自有的 SQLite 迁移。

规则：spec.md 要求 R1、R14；字段：interfaces.md 第一节。
声明：`<migrations_root>/<模块名>/<顺序号>_<名字>.sql`；文件头用 SQL 注释
`-- tables: a, b` 声明本文件创建的表。顺序 = 模块名升序 + 顺序号升序；
版本号按项目独立计数。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

SUFFIX, BUSY_TIMEOUT = ".sql", 10  # 秒；并发排队等锁，不立刻报 database is locked
PRAGMAS = ("journal_mode=WAL", "foreign_keys=ON", "busy_timeout=10000")
PRAGMA_RETRIES, PRAGMA_BACKOFF = 20, 0.05  # 并发首建库时排队重试
VERSION_TABLE, REQUEST_TABLE = "schema_migrations", "migration_requests"
PROJECT_TABLE = "migration_project"
BOOKKEEPING = (VERSION_TABLE, REQUEST_TABLE, PROJECT_TABLE)

SCOPE, CONFLICT = "PROJECT_SCOPE_VIOLATION", "CONFLICT"
REUSE, ORDER = "IDEMPOTENCY_KEY_REUSE", "MIGRATION_ORDER_CONFLICT"
FAILED, NO_ROOT = "MIGRATION_FAILED", "MIGRATIONS_ROOT_MISSING"
INVALID = "INVALID_PAYLOAD"

BOOKKEEPING_DDL = (
    f"CREATE TABLE IF NOT EXISTS {PROJECT_TABLE} (project_id TEXT PRIMARY KEY)",
    f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (project_id TEXT NOT NULL,"
    " version INTEGER NOT NULL, module TEXT NOT NULL, seq INTEGER NOT NULL,"
    " name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL,"
    " PRIMARY KEY (project_id, version))",
    f"CREATE TABLE IF NOT EXISTS {REQUEST_TABLE} (project_id TEXT NOT NULL,"
    " actor_id TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL,"
    " result TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY"
    " KEY (project_id, actor_id, key))")

FILE = re.compile(r"^(?P<seq>[0-9]+)_(?P<slug>[^/\\]+)\.sql$")
CONTROL = re.compile(r"^(BEGIN|COMMIT|ROLLBACK|END|SAVEPOINT|RELEASE)\b", re.I)
TABLES = re.compile(r"^--[ \t]*tables[ \t]*:[ \t]*(?P<list>[^\n]*)$", re.M)


class SqliteMigrationError(Exception):
    """sqlite_migration 的唯一异常类；code 是稳定错误码。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def migrate(request: dict) -> dict:
    """按声明顺序应用未执行的迁移；整次一个事务，失败整体回滚。"""
    database = _scope_path(request["database_path"], "database_path")
    root = _scope_path(request["migrations_root"], "migrations_root")
    if not (project := str(request["project_id"]).strip()):
        raise SqliteMigrationError(SCOPE, "迁移必须带项目作用域", {"project_id": ""})
    actor_id, key = request["actor"]["actor_id"], request["idempotency_key"]
    fingerprint, connection = _fingerprint(request), None
    connection = _connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_bookkeeping(connection)
        _guard_project(connection, project)  # 先绑定并判项目归属，再谈幂等重放
        applied = _applied(connection, project)
        if (replay := _replay(connection, project, actor_id, key,
                              fingerprint)) is not None:
            connection.execute("COMMIT")  # 同键同请求：先提交再返回，锁立刻释放
            return replay
        plan, before = _plan(root), _tables(connection)  # 执行前的表：别家模块建的
        _apply(connection, plan, applied, project)
        if len(applied) < len(plan):
            _verify_tables(connection, plan, before)
        versions = [r["version"] for r in _applied(connection, project)]
        result = {"applied_versions": versions,
                  "current_version": versions[-1] if versions else 0}
        _remember(connection, project, actor_id, key, fingerprint, result)
        connection.execute("COMMIT")
        return result
    except Exception as exc:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        if isinstance(exc, SqliteMigrationError):
            raise
        raise SqliteMigrationError(FAILED, "迁移执行失败",
                                   {"reason": str(exc)}) from exc
    finally:
        connection.close()


def _scope_path(raw: str, field: str) -> Path:
    """数据库与迁移根都必须是真实绝对路径；相对路径和目录穿越一律拒绝。"""
    if not os.path.isabs(text := str(raw).strip()) or ".." in Path(text).parts:
        raise SqliteMigrationError(SCOPE, "路径须为绝对路径且不含目录穿越",
                                   {"field": field, "path": text})
    return Path(os.path.realpath(text))


def _connect(database: Path) -> sqlite3.Connection:
    """打开库文件并设 PRAGMA：切 WAL 要独占锁，并发首建同一个库时排队重试。"""
    try:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(database), isolation_level=None,
                                     timeout=BUSY_TIMEOUT)
        for attempt in range(PRAGMA_RETRIES + 1):
            try:
                for pragma in PRAGMAS:
                    connection.execute(f"PRAGMA {pragma}")
                return connection
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == PRAGMA_RETRIES:
                    raise
                time.sleep(PRAGMA_BACKOFF)
    except (OSError, sqlite3.Error) as exc:
        raise SqliteMigrationError(FAILED, "数据库打不开", {
            "database_path": str(database), "reason": str(exc)}) from exc


def _ensure_bookkeeping(connection: sqlite3.Connection) -> None:
    """本模块自己的台账：项目绑定、已执行迁移、幂等请求。"""
    for ddl in BOOKKEEPING_DDL:
        connection.execute(ddl)
    if "project_id" not in {r[1] for r in connection.execute(
            f"PRAGMA table_info({REQUEST_TABLE})")}:  # 旧结构无项目列，重建
        connection.execute(f"DROP TABLE {REQUEST_TABLE}")
        connection.execute(BOOKKEEPING_DDL[2])


def _guard_project(connection: sqlite3.Connection, project: str) -> None:
    """库归首个使用它的项目独占：零迁移首跑也落绑定，别家项目一律越权。"""
    who = (connection.execute(f"SELECT project_id FROM {PROJECT_TABLE}").fetchone()
           or connection.execute(f"SELECT project_id FROM {VERSION_TABLE} LIMIT 1")
           .fetchone())  # 绑定缺失时按已执行迁移回推归属，别让人凭空接管
    if who is not None and who[0] != project:
        raise SqliteMigrationError(
            SCOPE, "数据库已归另一个项目使用",
            {"project_id": project, "other_project_ids": [who[0]]})
    connection.execute(f"INSERT OR IGNORE INTO {PROJECT_TABLE} (project_id)"
                       " VALUES (?)", (project,))  # 归属确认后补写：旧库也落独占


def _applied(connection: sqlite3.Connection, project: str) -> list[dict]:
    """只读本项目的迁移记录，按版本升序。"""
    keys = ("version", "module", "seq", "name", "checksum")
    return [dict(zip(keys, r)) for r in connection.execute(
        f"SELECT {', '.join(keys)} FROM {VERSION_TABLE} WHERE project_id = ?"
        " ORDER BY version", (project,))]


def _replay(connection: sqlite3.Connection, project: str, actor_id: str,
            key: str, fingerprint: str) -> dict | None:
    """同项目、同 actor、同 key、同请求返回首次结果；同键异请求判复用错误。"""
    row = connection.execute(
        f"SELECT request_hash, result FROM {REQUEST_TABLE} WHERE project_id = ?"
        " AND actor_id = ? AND key = ?", (project, actor_id, key)).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        raise SqliteMigrationError(REUSE, "同一幂等键被不同请求复用",
                                   {"idempotency_key": key, "actor_id": actor_id})
    return json.loads(row[1])


def _remember(connection: sqlite3.Connection, project: str, actor_id: str,
              key: str, fingerprint: str, result: dict) -> None:
    connection.execute(
        f"INSERT INTO {REQUEST_TABLE} (project_id, actor_id, key, request_hash,"
        " result, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project, actor_id, key, fingerprint, json.dumps(result, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()))


def _plan(root: Path) -> list[dict]:
    """读迁移根，按模块名升序 + 顺序号升序排出执行计划。"""
    if not root.is_dir():
        raise SqliteMigrationError(
            NO_ROOT, "迁移根不存在", {"migrations_root": str(root)})
    plan: list[dict] = []
    for module_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        seqs: list[int] = []
        for path in sorted(p for p in module_dir.iterdir()
                           if p.is_file() and p.suffix.lower() == SUFFIX):
            if (match := FILE.match(path.name)) is None:
                raise SqliteMigrationError(
                    FAILED, "迁移文件名不合 `<顺序号>_<名字>.sql`", {"path": str(path)})
            if not Path(os.path.realpath(path)).is_relative_to(root):
                raise SqliteMigrationError(SCOPE, "迁移文件指到迁移根之外",
                                           {"path": str(path)})
            text, seq = path.read_text(encoding="utf-8"), int(match.group("seq"))
            seqs.append(seq)
            plan.append({"module": module_dir.name, "seq": seq, "text": text,
                         "name": match.group("slug"), "path": path,
                         "checksum": hashlib.sha256(text.encode()).hexdigest(),
                         "tables": _declared(text, path)})
        if seqs and seqs != list(range(1, len(seqs) + 1)):
            raise SqliteMigrationError(ORDER, "同一模块的顺序号必须从 1 起连续",
                                       {"module": module_dir.name, "seqs": seqs})
    return plan


def _declared(text: str, path: Path) -> list[str]:
    """读文件头的 `-- tables: a, b` 声明；没有声明就一个表都不许建。"""
    if (match := TABLES.search(text)) is None:
        return []
    if names := [n.strip() for n in match.group("list").split(",") if n.strip()]:
        return names
    raise SqliteMigrationError(FAILED, "`-- tables:` 声明为空", {"path": str(path)})


def _apply(connection: sqlite3.Connection, plan: list[dict],
           applied: list[dict], project: str) -> None:
    """校验已执行前缀后，逐条执行未应用的迁移并记账；失败由外层整体回滚。"""
    if len(applied) > len(plan):
        raise SqliteMigrationError(ORDER, "已执行的迁移在声明里找不到",
                                   {"applied": len(applied), "declared": len(plan)})
    for index, entry in enumerate(plan):
        if index < len(applied):
            row = applied[index]
            if (row["module"], row["seq"], row["name"]) != (
                    entry["module"], entry["seq"], entry["name"]):
                raise SqliteMigrationError(
                    ORDER, "新迁移插到了已执行迁移之前", {"version": row["version"],
                    "applied": row["name"], "declared": entry["name"]})
            if row["checksum"] != entry["checksum"]:
                raise SqliteMigrationError(CONFLICT, "已执行的迁移文件内容被改动",
                                           {"module": row["module"],
                                            "name": row["name"]})
            continue
        try:
            for statement in _statements(entry["text"]):
                connection.execute(statement)
        except sqlite3.Error as exc:
            raise SqliteMigrationError(
                FAILED, "迁移语句执行失败", {"name": entry["name"], "reason": str(exc),
                "module": entry["module"]}) from exc
        connection.execute(
            f"INSERT INTO {VERSION_TABLE} (project_id, version, module, seq, name,"
            " checksum, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project, index + 1, entry["module"], entry["seq"], entry["name"],
             entry["checksum"], datetime.now(timezone.utc).isoformat()))


def _statements(text: str) -> list[str]:
    """按完整语句切分：字符串与注释里的分号不算边界；逐字符累积，
    `complete_statement` 真即切一条，同一行两条也能分开。"""
    statements, buffer = [], ""
    for char in text:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            if buffer.strip() != ";":
                statements.append(buffer)
            buffer = ""
    if code := _first_code(buffer):  # 末尾残留语句不算整条，判不完整
        raise SqliteMigrationError(FAILED, "迁移文件末尾有不完整语句",
                                   {"tail": code[:80]})
    for statement in statements:
        if CONTROL.match(code := _first_code(statement)):
            raise SqliteMigrationError(FAILED, "迁移文件不得自带事务控制语句",
                                       {"statement": code[:40]})
    return statements


def _first_code(block: str) -> str:
    """一段 SQL 的第一条非注释语句；头注释不当语句。"""
    return next((s.strip() for s in block.splitlines()
                 if s.strip() and not s.strip().startswith("--")), "")


def _tables(connection: sqlite3.Connection) -> set[str]:
    """整库现有表名，不含 sqlite 内部表。"""
    return {r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE"
        " 'sqlite_%'")}


def _verify_tables(connection: sqlite3.Connection, plan: list[dict],
                   before: set[str]) -> None:
    """只许创建本次声明的表：按执行前后差集判，别家模块的表不算越界。"""
    declared = set(BOOKKEEPING).union(*(e["tables"] for e in plan))
    if extra := sorted((_tables(connection) - before) - declared):
        raise SqliteMigrationError(FAILED, "迁移建了未声明的表",
                                   {"undeclared_tables": extra})


def _fingerprint(request: dict) -> str:
    """请求指纹：只取影响迁移结果的字段，供幂等重放比对。"""
    material = {k: str(request.get(k, "")).strip()
                for k in ("project_id", "database_path", "migrations_root")}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
