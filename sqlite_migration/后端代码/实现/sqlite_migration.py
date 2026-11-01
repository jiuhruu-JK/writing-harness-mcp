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
BOOKKEEPING = (VERSION_TABLE, REQUEST_TABLE)

SCOPE, CONFLICT = "PROJECT_SCOPE_VIOLATION", "CONFLICT"
REUSE, ORDER = "IDEMPOTENCY_KEY_REUSE", "MIGRATION_ORDER_CONFLICT"
FAILED, NO_ROOT = "MIGRATION_FAILED", "MIGRATIONS_ROOT_MISSING"
INVALID = "INVALID_PAYLOAD"

BOOKKEEPING_DDL = (
    f"CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (project_id TEXT NOT NULL,"
    " version INTEGER NOT NULL, module TEXT NOT NULL, seq INTEGER NOT NULL,"
    " name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL,"
    " PRIMARY KEY (project_id, version))",
    f"CREATE TABLE IF NOT EXISTS {REQUEST_TABLE} (actor_id TEXT NOT NULL,"
    " key TEXT NOT NULL, request_hash TEXT NOT NULL, result TEXT NOT NULL,"
    " recorded_at TEXT NOT NULL, PRIMARY KEY (actor_id, key))")

FILE = re.compile(r"^(?P<seq>[0-9]+)_(?P<slug>[^/\\]+)\.sql$")
CONTROL = re.compile(r"^(BEGIN|COMMIT|ROLLBACK|END|SAVEPOINT|RELEASE)\b", re.I)
TABLES = re.compile(r"^--\s*tables\s*:\s*(?P<list>.*)$", re.M)


class SqliteMigrationError(Exception):
    """sqlite_migration 的唯一异常类；code 是稳定错误码。"""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def migrate(request: dict) -> dict:
    """按声明顺序应用未执行的迁移；整个过程一个事务，失败整体回滚。"""
    database = _scope_path(request["database_path"], "database_path")
    root = _scope_path(request["migrations_root"], "migrations_root")
    project = str(request["project_id"]).strip()
    if not project:
        raise SqliteMigrationError(SCOPE, "迁移必须带项目作用域", {"project_id": ""})
    actor_id = request["actor"]["actor_id"]
    key = request["idempotency_key"]
    fingerprint = _fingerprint(request)

    connection = _connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _ensure_bookkeeping(connection)
        applied = _applied(connection, project)  # 先判项目归属，再谈幂等重放
        if (replay := _replay(connection, actor_id, key, fingerprint)) is not None:
            connection.execute("COMMIT")  # 同键同请求：先提交再返回，锁立刻释放
            return replay
        plan = _plan(root)
        _guard_order(plan, applied)
        _apply(connection, plan, applied, project)
        if len(applied) < len(plan):  # 本次确实建了东西才校验，无新迁移不拦外部表
            _verify_tables(connection, plan)
        result = _result(connection, project)
        _remember(connection, actor_id, key, fingerprint, result)
        connection.execute("COMMIT")
        return result
    except Exception as exc:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        if isinstance(exc, SqliteMigrationError):
            raise
        raise SqliteMigrationError(
            FAILED, "迁移执行失败", {"reason": str(exc)}) from exc
    finally:
        connection.close()


def _scope_path(raw: str, field: str) -> Path:
    """数据库与迁移根都必须是真实绝对路径；相对路径和目录穿越一律拒绝。"""
    if not os.path.isabs(text := str(raw).strip()) or ".." in Path(text).parts:
        raise SqliteMigrationError(SCOPE, "路径必须是绝对路径且不含目录穿越",
                                   {"field": field, "path": text})
    return Path(os.path.realpath(text))


def _connect(database: Path) -> sqlite3.Connection:
    """打开库文件：WAL、外键、手动事务。"""
    try:
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(database), isolation_level=None,
                                     timeout=BUSY_TIMEOUT)
        _pragmas(connection)
    except (OSError, sqlite3.Error) as exc:
        raise SqliteMigrationError(
            FAILED, "数据库打不开", {"database_path": str(database),
                                     "reason": str(exc)}) from exc
    return connection


def _pragmas(connection: sqlite3.Connection) -> None:
    """切 WAL 要独占锁：并发首建同一个库时排队重试，别把同伴顶掉。"""
    for attempt in range(PRAGMA_RETRIES + 1):
        try:
            for pragma in PRAGMAS:
                connection.execute(f"PRAGMA {pragma}")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == PRAGMA_RETRIES:
                raise
            time.sleep(PRAGMA_BACKOFF)

def _ensure_bookkeeping(connection: sqlite3.Connection) -> None:
    """本模块自己的两本台账：已执行迁移、幂等请求。"""
    for ddl in BOOKKEEPING_DDL:
        connection.execute(ddl)


def _applied(connection: sqlite3.Connection, project: str) -> list[dict]:
    """只读本项目的迁移记录；库里出现别家项目记录即判跨项目越权。"""
    rows = connection.execute(f"SELECT project_id, version, module, seq, name,"
                              f" checksum FROM {VERSION_TABLE}").fetchall()
    if foreign := sorted({r[0] for r in rows if r[0] != project}):
        raise SqliteMigrationError(SCOPE, "数据库里有其他项目的迁移记录",
                                   {"project_id": project, "other_project_ids": foreign})
    keys = ("version", "module", "seq", "name", "checksum")
    return [dict(zip(keys, row[1:])) for row in rows]


def _replay(connection: sqlite3.Connection, actor_id: str, key: str,
            fingerprint: str) -> dict | None:
    """同 actor、同 key、同请求返回首次结果；同 key 异请求判复用错误。"""
    row = connection.execute(
        f"SELECT request_hash, result FROM {REQUEST_TABLE}"
        " WHERE actor_id = ? AND key = ?", (actor_id, key)).fetchone()
    if row is None:
        return None
    if row[0] != fingerprint:
        raise SqliteMigrationError(REUSE, "同一幂等键被不同请求复用",
                                   {"idempotency_key": key, "actor_id": actor_id})
    return json.loads(row[1])


def _remember(connection: sqlite3.Connection, actor_id: str, key: str,
              fingerprint: str, result: dict) -> None:
    connection.execute(
        f"INSERT INTO {REQUEST_TABLE} (actor_id, key, request_hash, result,"
        " recorded_at) VALUES (?, ?, ?, ?, ?)",
        (actor_id, key, fingerprint, json.dumps(result, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat()))


def _result(connection: sqlite3.Connection, project: str) -> dict:
    """本项目已执行版本列表与当前版本。"""
    versions = [r[0] for r in connection.execute(
        f"SELECT version FROM {VERSION_TABLE} WHERE project_id = ?"
        " ORDER BY version", (project,))]
    return {"applied_versions": versions, "current_version": versions[-1] if versions else 0}


def _plan(root: Path) -> list[dict]:
    """读迁移根，按模块名升序 + 顺序号升序排出执行计划。"""
    if not root.is_dir():
        raise SqliteMigrationError(
            NO_ROOT, "迁移根不存在", {"migrations_root": str(root)})
    plan: list[dict] = []
    for module_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(p for p in module_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == SUFFIX)
        seqs = []
        for path in files:
            match = FILE.match(path.name)
            if match is None:
                raise SqliteMigrationError(
                    FAILED, "迁移文件名不合 `<顺序号>_<名字>.sql`",
                    {"path": str(path)})
            if not Path(os.path.realpath(path)).is_relative_to(root):
                raise SqliteMigrationError(
                    SCOPE, "迁移文件指到迁移根之外", {"path": str(path)})
            text, seq = path.read_text(encoding="utf-8"), int(match.group("seq"))
            seqs.append(seq)
            plan.append({"module": module_dir.name, "seq": seq,
                         "name": match.group("slug"), "path": path,
                         "checksum": hashlib.sha256(text.encode()).hexdigest(),
                         "text": text, "tables": _declared(text, path)})
        if seqs and seqs != list(range(1, len(seqs) + 1)):
            raise SqliteMigrationError(ORDER, "同一模块的顺序号必须从 1 起连续",
                                       {"module": module_dir.name, "seqs": seqs})
    return plan


def _declared(text: str, path: Path) -> list[str]:
    """读文件头的 `-- tables: a, b` 声明；没有声明就一个表都不许建。"""
    if (match := TABLES.search(text)) is None:
        return []
    if not (names := [n.strip() for n in match.group("list").split(",") if n.strip()]):
        raise SqliteMigrationError(FAILED, "`-- tables:` 声明为空",
                                   {"path": str(path)})
    return names


def _guard_order(plan: list[dict], applied: list[dict]) -> None:
    """已执行顺序须是声明顺序的前缀，且文件内容不得改动。"""
    if len(applied) > len(plan):
        raise SqliteMigrationError(ORDER, "已执行的迁移在声明里找不到",
                                   {"applied": len(applied), "declared": len(plan)})
    for row, entry in zip(applied, plan):
        if (row["module"], row["seq"], row["name"]) != \
                (entry["module"], entry["seq"], entry["name"]):
            raise SqliteMigrationError(ORDER, "新迁移插到了已执行迁移之前",
                                       {"version": row["version"],
                                        "applied": row["name"],
                                        "declared": entry["name"]})
        if row["checksum"] != entry["checksum"]:
            raise SqliteMigrationError(CONFLICT, "已执行的迁移文件内容被改动",
                                       {"module": row["module"],
                                        "name": row["name"]})


def _apply(connection: sqlite3.Connection, plan: list[dict],
           applied: list[dict], project: str) -> None:
    """在调用方的事务里逐条执行未应用的迁移；失败由外层整体回滚。"""
    for index in range(len(applied), len(plan)):
        entry = plan[index]
        try:
            for statement in _statements(entry["text"]):
                connection.execute(statement)
        except sqlite3.Error as exc:
            raise SqliteMigrationError(FAILED, "迁移语句执行失败",
                                       {"module": entry["module"], "reason": str(exc),
                                        "name": entry["name"]}) from exc
        connection.execute(
            f"INSERT INTO {VERSION_TABLE} (project_id, version, module, seq, name,"
            " checksum, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project, index + 1, entry["module"], entry["seq"], entry["name"],
             entry["checksum"], datetime.now(timezone.utc).isoformat()))


def _statements(text: str) -> list[str]:
    """按完整语句切分：字符串与注释里的分号不算边界。

    逐字符累积，`complete_statement` 真即切一条，同一行两条也能分开。
    """
    statements: list[str] = []
    buffer = ""
    for char in text:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            if buffer.strip() != ";":
                statements.append(buffer)
            buffer = ""
    tail = [s.strip() for s in buffer.splitlines()
            if s.strip() and not s.strip().startswith("--")]
    if tail:  # 末尾只剩空白与整行注释时不算残留语句
        raise SqliteMigrationError(FAILED, "迁移文件末尾有不完整语句",
                                   {"tail": tail[0][:80]})
    for statement in statements:  # 头注释之后的语句也要认出 BEGIN
        head = next((s.strip() for s in statement.splitlines()
                     if s.strip() and not s.strip().startswith("--")), "")
        if CONTROL.match(head):
            raise SqliteMigrationError(FAILED, "迁移文件不得自带事务控制语句",
                                       {"statement": head[:40]})
    return statements


def _verify_tables(connection: sqlite3.Connection, plan: list[dict]) -> None:
    """迁移只许创建自己声明的表；多建一张即判失败——在提交之前查。"""
    declared = set(BOOKKEEPING).union(*(e["tables"] for e in plan))
    actual = {r[0] for r in connection.execute("SELECT name FROM sqlite_master"
                                               " WHERE type='table'"
                                               " AND name NOT LIKE 'sqlite_%'")}
    if extra := sorted(actual - declared):
        raise SqliteMigrationError(FAILED, "迁移建了未声明的表",
                                   {"undeclared_tables": extra})


def _fingerprint(request: dict) -> str:
    """请求指纹：只取影响迁移结果的字段，供幂等重放比对。"""
    material = {"project_id": str(request.get("project_id", "")).strip(),
                "database_path": str(request["database_path"]).strip(),
                "migrations_root": str(request["migrations_root"]).strip()}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
