"""project_registry 同步测试：正常、失败、越权三类路径。

验收条款来自 specs/2026-11-01-writing-harness-mcp.spec.md 要求 R1
与 specs/2026-11-01-writing-harness-mcp.interfaces.md 第一节。
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "后端代码"))

_CMD_PATH = ROOT / "后端代码" / "命令.py"
_spec = importlib.util.spec_from_file_location("pr_test_cmd", _CMD_PATH)
命令 = importlib.util.module_from_spec(_spec)
sys.modules["pr_test_cmd"] = 命令
_spec.loader.exec_module(命令)
run = 命令.run
ProjectRegistryError = 命令.ProjectRegistryError

REGISTRY_DIR = ".writing-harness"
DB_FILE = "registry.db"
DATA_KEYS = {"project_id", "schema_version", "data_root"}


def payload(action: str, root: Path, **extra) -> dict:
    base = {
        "request_id": "req-1",
        "project_id": "",
        "actor": {"actor_id": "human-1", "role": "human",
                  "client_instance_id": "client-1"},
        "idempotency_key": "key-1",
        "action": action,
        "root_path": str(root),
        "name": "",
    }
    base.update(extra)
    return base


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "book"


def registered(request_payload: dict) -> dict:
    result = run(request_payload)
    assert result["ok"] is True, result
    return result["data"]


def read_payload(action: str, root: Path, **extra) -> dict:
    """读操作的入参：不带幂等键。"""
    read = {k: v for k, v in payload(action, root, **extra).items()
            if k != "idempotency_key"}
    return read


# ---------- 正常路径 ----------

def test_register_returns_stable_identity(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    assert data["schema_version"] == 1
    assert data["project_id"]
    assert data["data_root"]["root_path"] == str(Path(os.path.realpath(root)))


def test_register_data_keys_match_contract(root: Path) -> None:
    """接口总表规定返回三键，多一个也不行。"""
    data = registered(payload("register", root, name="长夜"))
    assert set(data) == DATA_KEYS
    scope = {"project_id": data["project_id"]}
    assert set(run(read_payload("open", root, **scope))["data"]) == DATA_KEYS
    assert set(run(read_payload("resolve", root, name="manuscript",
                                **scope))["data"]) == DATA_KEYS


def test_register_is_idempotent_for_same_request(root: Path) -> None:
    first = run(payload("register", root, name="长夜"))
    second = run(payload("register", root, name="长夜"))
    assert first["data"]["project_id"] == second["data"]["project_id"]


def test_register_persists_in_one_transaction(root: Path) -> None:
    """项目行与幂等台账落在同一个 SQLite 文件里。"""
    data = registered(payload("register", root, name="长夜"))
    db = root / REGISTRY_DIR / DB_FILE
    assert db.is_file()
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT project_id, name FROM projects").fetchall()
        cached = conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()[0]
    finally:
        conn.close()
    assert rows == [(data["project_id"], "长夜")]
    assert cached == 1


def test_open_returns_same_project(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    opened = run(read_payload("open", root, project_id=data["project_id"]))
    assert opened["ok"] is True
    assert opened["data"]["project_id"] == data["project_id"]


def test_open_needs_no_idempotency_key(root: Path) -> None:
    """读操作不必带幂等键（接口总表只要求写模块带）。"""
    data = registered(payload("register", root, name="长夜"))
    assert run(read_payload("open", root,
                            project_id=data["project_id"]))["ok"] is True


def test_resolve_needs_no_idempotency_key(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    assert run(read_payload("resolve", root, name="chapters/a.md",
                            project_id=data["project_id"]))["ok"] is True


# ---------- 失败路径 ----------

def test_missing_required_field_rejected(root: Path) -> None:
    bad = payload("register", root, name="长夜")
    bad.pop("actor")
    result = run(bad)
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_PAYLOAD"
    assert "actor" in result["error"]["details"]["missing"]


def test_unknown_action_rejected(root: Path) -> None:
    result = run(payload("delete", root, name="长夜"))
    assert result["error"]["code"] == "INVALID_PAYLOAD"
    assert result["error"]["details"]["action"] == "delete"


@pytest.mark.parametrize("field", ["request_id", "idempotency_key"])
def test_blank_envelope_fields_rejected(root: Path, field: str) -> None:
    result = run(payload("register", root, name="长夜", **{field: "   "}))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_actor_without_id_rejected(root: Path) -> None:
    result = run(payload("register", root, name="长夜",
                         **{"actor": {"role": "human"}}))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_project_id_must_be_string(root: Path) -> None:
    result = run(payload("register", root, name="长夜", project_id=123))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_blank_root_path_rejected(root: Path) -> None:
    result = run(payload("register", root, name="长夜", root_path="  "))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_register_without_name_rejected(root: Path) -> None:
    result = run(payload("register", root))
    assert result["error"]["code"] == "INVALID_PAYLOAD"
    assert result["error"]["details"]["field"] == "name"


def test_non_dict_payload_rejected() -> None:
    result = run(["not", "a", "dict"])  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_relative_root_rejected(root: Path) -> None:
    result = run(payload("register", root, name="长夜", root_path="relative/path"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_root_with_traversal_rejected(root: Path) -> None:
    result = run(payload("register", root, name="长夜",
                         root_path="/tmp/../etc/passwd"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_same_root_two_names_conflict(root: Path) -> None:
    registered(payload("register", root, name="长夜"))
    result = run(payload("register", root, name="另一本", idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "CONFLICT"
    assert result["error"]["details"]["registered_name"] == "长夜"


def test_same_key_different_request_rejected(root: Path) -> None:
    registered(payload("register", root, name="长夜"))
    result = run(payload("register", root, name="另一本"))
    assert result["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_same_key_replays_first_result(root: Path) -> None:
    first = registered(payload("register", root, name="长夜"))
    replay = run(payload("register", root, name="长夜"))
    assert replay["data"] == first


def test_nested_root_cannot_become_second_project(root: Path) -> None:
    """已登记项目根内的目录不能登记为第二个项目（否则可绕过项目边界）。"""
    registered(payload("register", root, name="长夜"))
    result = run(payload("register", root / "sub", name="子项目",
                         idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "CONFLICT"
    assert result["error"]["details"]["registered_root"] == str(root)


def test_register_with_foreign_scope_rejected(root: Path) -> None:
    """登记新项目时带他人身份不得通过。"""
    result = run(payload("register", root, name="长夜", project_id="other-project"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_open_unregistered_root_rejected(root: Path) -> None:
    result = run(read_payload("open", root, project_id="any"))
    assert result["error"]["code"] == "PROJECT_NOT_REGISTERED"


def test_corrupt_registry_reports_code(root: Path) -> None:
    registered(payload("register", root, name="长夜"))
    db = root / REGISTRY_DIR / DB_FILE
    db.write_bytes(b"not a database")
    result = run(read_payload("open", root, project_id="x"))
    assert result["error"]["code"] in {"PROJECT_NOT_REGISTERED",
                                       "PROJECT_STORE_IO_ERROR"}


def test_store_unwritable_reports_io(root: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise OSError("no space")

    monkeypatch.setattr(sqlite3, "connect", boom)
    result = run(payload("register", root, name="长夜"))
    assert result["error"]["code"] == "PROJECT_STORE_IO_ERROR"


def test_transaction_failure_rolls_back_root_row(root: Path, monkeypatch) -> None:
    """登记写库中途失败时，项目行不落地，幂等台账也不落地。"""
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", boom)
    result = run(payload("register", root / "fresh", name="新书"))
    assert result["ok"] is False
    assert not (root / "fresh" / REGISTRY_DIR / DB_FILE).exists()


# ---------- 越权路径 ----------

def test_open_with_foreign_project_id_rejected(root: Path) -> None:
    registered(payload("register", root, name="长夜"))
    result = run(read_payload("open", root, project_id="other-project"))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_open_without_scope_rejected(root: Path) -> None:
    """读操作必须带项目作用域，空作用域不得读他人档案。"""
    registered(payload("register", root, name="长夜"))
    result = run(read_payload("open", root, project_id=""))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_cross_project_read_blocked(tmp_path: Path) -> None:
    """持甲书身份读乙书根：一条记录都读不到。"""
    first_root = tmp_path / "book-a"
    second_root = tmp_path / "book-b"
    first = registered(payload("register", first_root, name="甲书"))
    registered(payload("register", second_root, name="乙书", idempotency_key="key-2"))
    leaked = run(read_payload("open", second_root, project_id=first["project_id"]))
    assert leaked["ok"] is False
    assert leaked["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert leaked["error"]["details"]["registered_project_id"]


def test_empty_scope_cannot_read_other_root(tmp_path: Path) -> None:
    """空作用域也不得读到他人项目身份（R1 跨项目查询场景）。"""
    second_root = tmp_path / "book-b"
    registered(payload("register", second_root, name="乙书"))
    result = run(read_payload("open", second_root, project_id=""))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_without_scope_rejected(root: Path) -> None:
    registered(payload("register", root, name="长夜"))
    result = run(read_payload("resolve", root, name="manuscript"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_absolute_path(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    result = run(read_payload("resolve", root, name="/etc/passwd",
                              project_id=data["project_id"]))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_traversal(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    result = run(read_payload("resolve", root, name="../outside.md",
                              project_id=data["project_id"]))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_blank_name(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    result = run(read_payload("resolve", root, name="   ",
                              project_id=data["project_id"]))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_resolve_rejects_registry_dir(root: Path) -> None:
    """登记目录自身也是禁区：读到它就等于读到本模块的内部档案。"""
    data = registered(payload("register", root, name="长夜"))
    result = run(read_payload("resolve", root, name=f"{REGISTRY_DIR}/{DB_FILE}",
                              project_id=data["project_id"]))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_escape_symlink(root: Path, tmp_path: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    outside = tmp_path / "outside.md"
    outside.write_text("外部内容", encoding="utf-8")
    os.symlink(outside, root / "escape.md")
    result = run(read_payload("resolve", root, name="escape.md",
                              project_id=data["project_id"]))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert result["error"]["details"]["resolved_path"] == str(outside)


def test_resolve_allows_symlink_inside_root(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    target = root / "real.md"
    target.write_text("根内内容", encoding="utf-8")
    os.symlink(target, root / "alias.md")
    assert run(read_payload("resolve", root, name="alias.md",
                            project_id=data["project_id"]))["ok"] is True


def test_resolve_path_inside_root_succeeds(root: Path) -> None:
    data = registered(payload("register", root, name="长夜"))
    (root / "chapters").mkdir(parents=True)
    result = run(read_payload("resolve", root, name="chapters/第一章.md",
                              project_id=data["project_id"]))
    assert result["ok"] is True


def test_errors_are_single_class_with_code(root: Path) -> None:
    """每个模块一个异常类：实现层抛同一个类，薄壳映射成稳定错误码。"""
    with pytest.raises(ProjectRegistryError) as caught:
        命令._IMPL.register(payload("register", root, name="长夜",
                                    root_path="rel"))
    assert caught.value.code == "PROJECT_SCOPE_VIOLATION"
    assert caught.value.message
    assert caught.value.details["root_path"] == "rel"


# ---------- 边界分支 ----------

def test_impl_cache_returns_same_module() -> None:
    """入口的实现装载带缓存，重复调用不重复执行模块体。"""
    assert 命令._load_impl() is 命令._IMPL


def test_unexpected_exception_still_returns_envelope(root: Path,
                                                     monkeypatch) -> None:
    def boom(request):
        raise ValueError("实现内部炸了")

    monkeypatch.setattr(命令._IMPL, "register", boom)
    result = run(payload("register", root, name="长夜"))
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_PAYLOAD"
    assert result["error"]["details"]["reason"] == "实现内部炸了"


def test_register_transaction_error_reports_io(root: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(命令._IMPL, "_remember", boom)
    result = run(payload("register", root, name="长夜"))
    assert result["error"]["code"] == "PROJECT_STORE_IO_ERROR"


def test_register_integrity_error_reports_conflict(root: Path,
                                                  monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise sqlite3.IntegrityError("UNIQUE constraint failed")

    monkeypatch.setattr(命令._IMPL, "_remember", boom)
    result = run(payload("register", root, name="长夜"))
    assert result["error"]["code"] == "CONFLICT"


def test_register_existing_root_foreign_scope_rejected(root: Path) -> None:
    """已登记根上再登记时带他人身份，判作用域越权而非复用身份。"""
    data = registered(payload("register", root, name="长夜"))
    result = run(payload("register", root, name="长夜", idempotency_key="k-2",
                         project_id="other-project"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert result["error"]["details"]["registered_project_id"] == data["project_id"]


def test_register_existing_root_same_name_returns_identity(root: Path) -> None:
    """同名再登记（换幂等键）返回既有身份，不新建项目行。"""
    first = registered(payload("register", root, name="长夜"))
    again = run(payload("register", root, name="长夜", idempotency_key="key-2"))
    assert again["ok"] is True
    assert again["data"]["project_id"] == first["project_id"]


def test_read_connect_error_reports_io(root: Path, monkeypatch) -> None:
    registered(payload("register", root, name="长夜"))

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", boom)
    result = run(read_payload("open", root, project_id="any"))
    assert result["error"]["code"] == "PROJECT_STORE_IO_ERROR"


def test_bad_schema_reports_corrupt(root: Path, monkeypatch) -> None:
    """建表语句坏掉时报登记库损坏，而不是当成入参错误。"""
    monkeypatch.setattr(命令._IMPL, "SCHEMA", ("CREATE TABLE",))
    result = run(payload("register", root, name="长夜"))
    assert result["error"]["code"] == "PROJECT_REGISTRY_CORRUPT"


def test_open_root_with_no_project_row_rejected(root: Path) -> None:
    """库在但项目行没了：判未登记，不返回空身份。"""
    data = registered(payload("register", root, name="长夜"))
    db = root / REGISTRY_DIR / DB_FILE
    conn = sqlite3.connect(str(db), isolation_level=None)
    try:
        conn.execute("DELETE FROM projects")
    finally:
        conn.close()
    result = run(read_payload("open", root, project_id=data["project_id"]))
    assert result["error"]["code"] == "PROJECT_NOT_REGISTERED"


def test_rollback_swallows_sqlite_error(root: Path) -> None:
    """回滚本身失败时不掩盖原始错误。"""
    class Broken:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("no transaction is active")

    assert 命令._IMPL._safe_rollback(Broken()) is None


def test_outer_root_cannot_contain_registered_project(tmp_path: Path) -> None:
    """反序嵌套：先登记内层，再把外层登记成第二个项目也要拒。"""
    outer = tmp_path / "外层"
    inner = outer / "内2"
    inner.mkdir(parents=True)
    registered(payload("register", inner, name="内2"))
    result = run(payload("register", outer, name="外", idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "CONFLICT"
    assert result["error"]["details"]["nested_root"] == str(inner)


def test_symlink_to_registry_dir_rejected(root: Path) -> None:
    """绕字面不行：符号链接指向登记目录同样拒绝。"""
    data = registered(payload("register", root, name="长夜"))
    os.symlink(root / REGISTRY_DIR, root / "影")
    result = run(read_payload("resolve", root, name=f"影/{DB_FILE}",
                              project_id=data["project_id"]))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_existing_root_second_key_is_recorded(root: Path) -> None:
    """已登记根分支也写台账：同键换请求内容必被拒，不会静默通过。"""
    registered(payload("register", root, name="长夜"))
    assert run(payload("register", root, name="长夜",
                       idempotency_key="key-2"))["ok"] is True
    # 同 actor、同 key、换项目名 = 不同请求 → 复用判据先命中
    other = run(payload("register", root, name="另一本", idempotency_key="key-2"))
    assert other["ok"] is False
    assert other["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"
