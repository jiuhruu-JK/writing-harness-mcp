"""sqlite_migration 同步测试：正常、失败、越权三类路径。

验收条款来自 specs/2026-11-01-writing-harness-mcp.spec.md 要求 R1、R14。
"""

from __future__ import annotations

import importlib.util
import sqlite3
import threading
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "后端代码"))

_CMD_PATH = ROOT / "后端代码" / "命令.py"
_spec = importlib.util.spec_from_file_location("sm_test_cmd", _CMD_PATH)
命令 = importlib.util.module_from_spec(_spec)
sys.modules["sm_test_cmd"] = 命令
_spec.loader.exec_module(命令)
run = 命令.run

GOOD = "CREATE TABLE {name} (id INTEGER PRIMARY KEY);\n"
PROJECT = "proj-1"


def payload(database: Path, root: Path, **extra) -> dict:
    base = {
        "request_id": "req-1",
        "project_id": PROJECT,
        "actor": {"actor_id": "migrator", "role": "system",
                  "client_instance_id": "client-1"},
        "idempotency_key": "key-1",
        "database_path": str(database),
        "migrations_root": str(root),
    }
    base.update(extra)
    return base


def write_module(root: Path, module: str, seq: int, name: str,
                 tables: list[str]) -> Path:
    """在迁移根下写一个模块迁移文件，文件头声明它建哪些表。"""
    folder = root / module
    folder.mkdir(parents=True, exist_ok=True)
    body = "".join(GOOD.format(name=table) for table in tables)
    text = f"-- tables: {', '.join(tables)}\n{body}" if tables else body
    path = folder / f"{seq}_{name}.sql"
    path.write_text(text, encoding="utf-8")
    return path


def tables(database: Path) -> set[str]:
    connection = sqlite3.connect(str(database))
    try:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'")}
    finally:
        connection.close()


@pytest.fixture()
def layout(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    root.mkdir()
    write_module(root, "alpha", 1, "create_documents", ["documents"])
    write_module(root, "beta", 1, "create_events", ["events"])
    write_module(root, "beta", 2, "create_mirror", ["mirror_log"])
    return database, root


# ---------- 正常路径 ----------

def test_migrate_applies_all_in_order(layout) -> None:
    database, root = layout
    result = run(payload(database, root))
    assert result["ok"] is True
    data = result["data"]
    assert data["applied_versions"] == [1, 2, 3]
    assert data["current_version"] == 3
    assert tables(database) == {"documents", "events", "mirror_log",
                                "schema_migrations", "migration_requests"}


def test_migrate_is_idempotent(layout) -> None:
    database, root = layout
    first = run(payload(database, root))
    second = run(payload(database, root, idempotency_key="key-2"))
    assert second["data"] == first["data"]
    assert tables(database) == {"documents", "events", "mirror_log",
                                "schema_migrations", "migration_requests"}


def test_same_request_replays_first_result(layout) -> None:
    database, root = layout
    first = run(payload(database, root))
    replay = run(payload(database, root))
    assert replay["data"] == first["data"]


def test_bookkeeping_records_each_module(layout) -> None:
    database, root = layout
    run(payload(database, root))
    connection = sqlite3.connect(str(database))
    try:
        rows = connection.execute(
            "SELECT version, module, seq FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [(1, "alpha", 1), (2, "beta", 1), (3, "beta", 2)]


def test_incremental_migration_adds_only_new(layout, tmp_path: Path) -> None:
    database, root = layout
    run(payload(database, root))
    write_module(root, "gamma", 1, "create_later", ["later_table"])
    result = run(payload(database, root, idempotency_key="key-2"))
    assert result["data"]["applied_versions"] == [1, 2, 3, 4]
    assert "later_table" in tables(database)


def test_empty_root_is_noop(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    root = tmp_path / "migrations"
    root.mkdir()
    result = run(payload(database, root))
    assert result["ok"] is True
    assert result["data"]["applied_versions"] == []
    assert result["data"]["current_version"] == 0


def test_semicolon_inside_string_not_split(tmp_path: Path) -> None:
    """字符串里的分号不能被当成语句边界。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "seed", ["notes"])
    path = root / "alpha" / "1_seed.sql"
    path.write_text(
        "-- tables: notes\n"
        "CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT);\n"
        "INSERT INTO notes (body) VALUES ('a;b');\n",
        encoding="utf-8")
    result = run(payload(database, root))
    assert result["ok"] is True
    connection = sqlite3.connect(str(database))
    try:
        assert connection.execute("SELECT body FROM notes").fetchall() == [("a;b",)]
    finally:
        connection.close()


def test_two_statements_on_one_line_split(tmp_path: Path) -> None:
    """同一行写两条语句也要拆开执行，不能整行当成一条。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_pair.sql").write_text(
        "-- tables: first, second\n"
        "CREATE TABLE first (id INTEGER); CREATE TABLE second (id INTEGER);\n",
        encoding="utf-8")
    result = run(payload(database, root))
    assert result["ok"] is True
    assert {"first", "second"} <= tables(database)


def test_trailing_comment_after_last_statement_ok(tmp_path: Path) -> None:
    """最后一条语句后的纯注释尾巴不算不完整语句。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_tail.sql").write_text(
        "-- tables: tailed\n"
        "CREATE TABLE tailed (id INTEGER);\n"
        "-- 结尾注释\n",
        encoding="utf-8")
    result = run(payload(database, root))
    assert result["ok"] is True
    assert "tailed" in tables(database)


# ---------- 失败路径 ----------

def test_missing_field_rejected(tmp_path: Path) -> None:
    result = run({"request_id": "r"})
    assert result["error"]["code"] == "INVALID_PAYLOAD"
    assert "database_path" in result["error"]["details"]["missing"]


def test_non_dict_payload_rejected() -> None:
    result = run("nope")  # type: ignore[arg-type]
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_blank_idempotency_key_rejected(layout) -> None:
    database, root = layout
    result = run(payload(database, root, idempotency_key="  "))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_actor_without_id_rejected(layout) -> None:
    database, root = layout
    result = run(payload(database, root, **{"actor": {"role": "system"}}))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_project_id_must_be_string(layout) -> None:
    database, root = layout
    result = run(payload(database, root, project_id=7))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


@pytest.mark.parametrize("field", ["database_path", "migrations_root"])
def test_blank_or_relative_path_rejected(layout, field: str, tmp_path: Path) -> None:
    database, root = layout
    for bad in ("  ", "relative/dir"):
        result = run(payload(database, root, **{field: bad}))
        assert result["error"]["code"] == "INVALID_PAYLOAD"
        assert result["error"]["details"]["field"] == field


def test_relative_path_in_implementation_rejected(tmp_path: Path) -> None:
    """绕过薄壳直接调实现，越权路径仍被拒。"""
    SqliteMigrationError = 命令.SqliteMigrationError

    with pytest.raises(SqliteMigrationError) as caught:
        命令._IMPL.migrate({"request_id": "r", "project_id": "p",
                 "actor": {"actor_id": "a"}, "idempotency_key": "k",
                 "database_path": "rel.db", "migrations_root": str(tmp_path)})
    assert caught.value.code == "PROJECT_SCOPE_VIOLATION"


def test_traversal_path_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    result = run(payload(database, tmp_path, migrations_root="/tmp/../etc"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_missing_migrations_root_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    result = run(payload(database, tmp_path / "nowhere"))
    assert result["error"]["code"] == "MIGRATIONS_ROOT_MISSING"


def test_empty_module_dir_tolerated(tmp_path: Path) -> None:
    """只建了目录、还没补迁移文件的模块不阻断执行（先建目录后补文件）。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    (root / "empty_module").mkdir(parents=True)
    write_module(root, "alpha", 1, "first", ["documents"])
    result = run(payload(database, root))
    assert result["ok"] is True, result
    assert result["data"]["applied_versions"] == [1]


def test_migrations_root_with_no_modules(tmp_path: Path) -> None:
    """迁移根为空目录：没有可执行迁移，返回空结果而不是报错。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    root.mkdir()
    result = run(payload(database, root))
    assert result["ok"] is True, result
    assert result["data"] == {"applied_versions": [], "current_version": 0}


def test_bad_file_name_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "create.sql").write_text("-- tables: x\n", encoding="utf-8")
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"


def test_non_contiguous_sequence_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "one", ["a"])
    write_module(root, "alpha", 3, "three", ["c"])
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_ORDER_CONFLICT"


def test_failed_statement_rolls_back_that_migration(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "ok", ["kept"])
    path = root / "alpha" / "2_broken.sql"
    path.write_text(
        "-- tables: dropped\n"
        "CREATE TABLE dropped (id INTEGER);\n"
        "INSERT INTO missing_table VALUES (1);\n",
        encoding="utf-8")
    result = run(payload(database, root))
    assert result["ok"] is False
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert result["error"]["details"]["name"] == "broken"
    # 整次调用一个事务：第 2 条失败连第 1 条一起回滚，库里不留半张表
    assert "kept" not in tables(database)
    assert "dropped" not in tables(database)


def test_undeclared_table_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_sneaky.sql").write_text(
        "-- tables: only_one\n"
        "CREATE TABLE only_one (id INTEGER);\n"
        "CREATE TABLE smuggled (id INTEGER);\n",
        encoding="utf-8")
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert result["error"]["details"]["undeclared_tables"] == ["smuggled"]


def test_missing_tables_header_means_no_tables(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_plain.sql").write_text(
        "CREATE TABLE plain (id INTEGER);\n", encoding="utf-8")
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert result["error"]["details"]["undeclared_tables"] == ["plain"]


def test_empty_tables_declaration_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_blank.sql").write_text("-- tables: \n", encoding="utf-8")
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"


def test_unterminated_statement_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_partial.sql").write_text(
        "-- tables: half\nCREATE TABLE half (id INTEGER)", encoding="utf-8")
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert "tail" in result["error"]["details"]


def test_inserting_before_applied_rejected(layout) -> None:
    """新迁移排到已执行迁移之前 = 顺序冲突。"""
    database, root = layout
    run(payload(database, root))
    write_module(root, "aardvark", 1, "create_early", ["early_table"])
    result = run(payload(database, root, idempotency_key="key-2"))
    assert result["error"]["code"] == "MIGRATION_ORDER_CONFLICT"


def test_edited_applied_file_rejected(layout) -> None:
    database, root = layout
    run(payload(database, root))
    path = root / "alpha" / "1_create_documents.sql"
    path.write_text("-- tables: documents\n"
                    "CREATE TABLE documents (id INTEGER PRIMARY KEY, extra TEXT);\n",
                    encoding="utf-8")
    result = run(payload(database, root, idempotency_key="key-2"))
    assert result["error"]["code"] == "CONFLICT"


def test_more_applied_than_declared_rejected(layout) -> None:
    database, root = layout
    run(payload(database, root))
    write_module(root, "gamma", 1, "g", ["g_table"])
    run(payload(database, root, idempotency_key="key-2"))
    path = root / "gamma" / "1_g.sql"
    path.unlink()
    (root / "gamma").rmdir()
    result = run(payload(database, root, idempotency_key="key-3"))
    assert result["error"]["code"] == "MIGRATION_ORDER_CONFLICT"


def test_same_key_different_request_rejected(layout) -> None:
    database, root = layout
    run(payload(database, root))
    result = run(payload(database, root, project_id="proj-2"))
    assert result["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


# ---------- 越权路径 ----------

def test_symlink_migration_file_outside_root_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    outside = tmp_path / "outside.sql"
    outside.write_text("-- tables: stolen\nCREATE TABLE stolen (id INTEGER);\n",
                       encoding="utf-8")
    folder = root / "alpha"
    folder.mkdir(parents=True)
    (folder / "1_evil.sql").symlink_to(outside)
    result = run(payload(database, root))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert "stolen" not in tables(database)


def test_other_project_rejected(tmp_path: Path) -> None:
    """跨项目作用域：同一库文件已被别家项目占用时，另一个项目读不到也写不进。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    run(payload(database, root))
    result = run(payload(database, root, project_id="proj-2",
                         idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert result["error"]["details"]["other_project_ids"] == [PROJECT]


def test_missing_project_scope_rejected(tmp_path: Path) -> None:
    """读/写迁移台账必须带项目作用域。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    result = run(payload(database, root, project_id="  "))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_two_projects_use_separate_databases(tmp_path: Path) -> None:
    """每个项目用自己的库：两个项目各自从版本 1 起算，互不可见。"""
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    first = run(payload(tmp_path / "a.db", root))
    second = run(payload(tmp_path / "b.db", root, project_id="proj-2",
                        idempotency_key="key-2"))
    assert first["data"]["current_version"] == 1
    assert second["data"]["current_version"] == 1


def test_database_path_must_be_writable(tmp_path: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise PermissionError("read only")

    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    monkeypatch.setattr(sqlite3, "connect", boom)
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert result["error"]["details"]["reason"] == "read only"


def test_connect_failure_reports_failed(tmp_path: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", boom)
    result = run(payload(str(tmp_path / "state.db"), str(tmp_path / "migrations")))
    assert result["error"]["code"] == "MIGRATION_FAILED"


# ---------- 事务边界 ----------

def test_undeclared_table_leaves_nothing_and_retry_works(tmp_path: Path) -> None:
    """未声明表在提交前被拦下：库里不留任何表，改好文件后同一库可重试成功。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    path = root / "alpha" / "1_sneaky.sql"
    path.parent.mkdir(parents=True)
    path.write_text("-- tables: only_one\n"
                    "CREATE TABLE only_one (id INTEGER PRIMARY KEY);\n"
                    "CREATE TABLE smuggled (id INTEGER PRIMARY KEY);\n",
                    encoding="utf-8")
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert result["error"]["details"]["undeclared_tables"] == ["smuggled"]
    assert tables(database) == set()
    path.write_text("-- tables: only_one\n"
                    "CREATE TABLE only_one (id INTEGER PRIMARY KEY);\n",
                    encoding="utf-8")
    retried = run(payload(database, root, idempotency_key="key-2"))
    assert retried["ok"] is True, retried
    assert retried["data"]["applied_versions"] == [1]


def test_failure_leaves_no_bookkeeping_row(tmp_path: Path) -> None:
    """失败时台账也不落账：同键重试不会撞到上次的失败记录。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    path = root / "alpha" / "2_broken.sql"
    path.write_text("-- tables: ok_table\nCREATE TABLE ok_table (id INTEGER);\n"
                    "INSERT INTO nope VALUES (1);\n", encoding="utf-8")
    assert run(payload(database, root))["error"]["code"] == "MIGRATION_FAILED"
    assert tables(database) == set()


def test_concurrent_same_key_all_get_first_result(tmp_path: Path) -> None:
    """R14 重试场景：多线程同 actor 同键同请求，全部返回首次结果。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    results = []
    lock = threading.Lock()

    def work():
        out = run(payload(database, root))
        with lock:
            results.append(out)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 4
    # 全部成功且都拿到同一份首次结果
    assert all(item["ok"] is True for item in results), results
    assert {item["data"]["current_version"] for item in results} == {1}


def test_applied_version_is_per_project(tmp_path: Path) -> None:
    """版本号按项目计数：两个项目各用各的库，互不影响。"""
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "one", ["a"])
    write_module(root, "alpha", 2, "two", ["b"])
    first = run(payload(tmp_path / "a.db", root))
    second = run(payload(tmp_path / "b.db", root, project_id="proj-2",
                        idempotency_key="key-2"))
    assert first["data"] == {"applied_versions": [1, 2], "current_version": 2}
    assert second["data"] == {"applied_versions": [1, 2], "current_version": 2}


# ---------- 薄壳与异常边界 ----------

def test_impl_loader_is_cached() -> None:
    assert 命令._load_impl() is 命令._IMPL


def test_blank_request_id_rejected(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    result = run(payload(database, root, request_id="   "))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_unexpected_exception_returns_envelope(tmp_path: Path,
                                              monkeypatch) -> None:
    def boom(request):
        raise ValueError("实现内部炸了")

    monkeypatch.setattr(命令._IMPL, "migrate", boom)
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    result = run(payload(database, root))
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_PAYLOAD"
    assert result["error"]["details"]["reason"] == "实现内部炸了"


def test_rollback_failure_does_not_mask_original_error(tmp_path: Path,
                                                      monkeypatch) -> None:
    """回滚本身报错时，仍返回原始失败原因。"""
    database = tmp_path / "state.db"
    root = tmp_path / "migrations"
    write_module(root, "alpha", 1, "first", ["documents"])
    path = root / "alpha" / "2_broken.sql"
    path.write_text("-- tables: ok_table\nCREATE TABLE ok_table (id INTEGER);\n"
                    "INSERT INTO nope VALUES (1);\n", encoding="utf-8")
    original = 命令._IMPL._connect

    def broken_connect(database):
        conn = original(database)

        class Proxy:
            def __getattr__(self, name):
                return getattr(conn, name)

            def execute(self, sql, *args, **kwargs):
                if sql == "ROLLBACK":
                    raise sqlite3.OperationalError("no transaction is active")
                return conn.execute(sql, *args, **kwargs)

        return Proxy()

    monkeypatch.setattr(命令._IMPL, "_connect", broken_connect)
    result = run(payload(database, root))
    assert result["error"]["code"] == "MIGRATION_FAILED"
    assert result["error"]["details"]["name"] == "broken"
