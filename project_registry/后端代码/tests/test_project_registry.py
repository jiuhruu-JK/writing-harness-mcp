"""project_registry 同步测试：正常、失败、越权三类路径。

验收条款来自 specs/2026-11-01-writing-harness-mcp.spec.md 要求 R1。
"""

from __future__ import annotations

import importlib.util
import json
import os
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
MARKER = "project.json"
JOURNAL = "idempotency.json"


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


# ---------- 正常路径 ----------

def test_register_returns_stable_identity(root: Path) -> None:
    result = run(payload("register", root, name="长夜"))
    assert result["ok"] is True
    data = result["data"]
    assert data["schema_version"] == 1
    assert data["project_id"]
    assert data["data_root"]["root_path"] == str(Path(os.path.realpath(root)))


def test_register_is_idempotent_for_same_request(root: Path) -> None:
    first = run(payload("register", root, name="长夜"))
    second = run(payload("register", root, name="长夜"))
    assert first["data"]["project_id"] == second["data"]["project_id"]


def test_register_creates_marker_and_journal(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    marker = root / REGISTRY_DIR / MARKER
    journal = root / REGISTRY_DIR / JOURNAL
    assert marker.is_file() and journal.is_file()
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["name"] == "长夜"


def test_open_returns_same_project(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    opened = run(payload("open", root, idempotency_key="key-2"))
    assert opened["ok"] is True
    assert opened["data"]["project_id"] == registered["data"]["project_id"]


def test_open_with_matching_scope_succeeds(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    project_id = registered["data"]["project_id"]
    opened = run(payload("open", root, project_id=project_id, idempotency_key="key-2"))
    assert opened["ok"] is True


def test_open_tolerates_unregistered_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "空"
    result = run(payload("open", missing, idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_NOT_REGISTERED"


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
    run(payload("register", root, name="长夜"))
    result = run(payload("register", root, name="另一本",
                         idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "CONFLICT"
    assert result["error"]["details"]["registered_name"] == "长夜"


def test_same_key_different_request_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    result = run(payload("register", root, name="另一本"))
    assert result["error"]["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_corrupt_marker_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    marker = root / REGISTRY_DIR / MARKER
    marker.write_text("{ not json", encoding="utf-8")
    result = run(payload("open", root, idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_MARKER_CORRUPT"


def test_marker_missing_fields_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    marker = root / REGISTRY_DIR / MARKER
    marker.write_text(json.dumps({"name": "长夜"}), encoding="utf-8")
    result = run(payload("open", root, idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_MARKER_CORRUPT"


def test_marker_unreadable_reports_store_io(root: Path, monkeypatch) -> None:
    run(payload("register", root, name="长夜"))
    marker = root / REGISTRY_DIR / MARKER

    def boom(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", boom)
    result = run(payload("open", root, idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_STORE_IO_ERROR"
    assert str(marker) in result["error"]["details"]["path"]


def test_journal_not_a_list_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    journal = root / REGISTRY_DIR / JOURNAL
    journal.write_text(json.dumps({"actor_id": "x"}), encoding="utf-8")
    result = run(payload("register", root, name="另一本",
                         idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_MARKER_CORRUPT"


def test_journal_corrupt_json_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    journal = root / REGISTRY_DIR / JOURNAL
    journal.write_text("[ not json", encoding="utf-8")
    result = run(payload("register", root, name="长夜", idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_MARKER_CORRUPT"


def test_store_dir_unwritable_reports_store_io(root: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise OSError("no space")

    monkeypatch.setattr("tempfile.NamedTemporaryFile", boom)
    result = run(payload("register", root, name="长夜"))
    assert result["error"]["code"] == "PROJECT_STORE_IO_ERROR"


def test_write_failure_cleans_temp_file(root: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    result = run(payload("register", root, name="长夜"))
    assert result["error"]["code"] == "PROJECT_STORE_IO_ERROR"
    assert not list((root / REGISTRY_DIR).glob(".tmp-*"))


# ---------- 越权路径 ----------

def test_open_with_foreign_project_id_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    result = run(payload("open", root, project_id="other-project",
                         idempotency_key="key-2"))
    assert result["ok"] is False
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert result["error"]["details"]["project_id"] == "other-project"


def test_resolve_without_scope_rejected(root: Path) -> None:
    run(payload("register", root, name="长夜"))
    result = run(payload("resolve", root, name="manuscript", idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_absolute_path(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    result = run(payload("resolve", root, name="/etc/passwd",
                         project_id=registered["data"]["project_id"],
                         idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_traversal(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    result = run(payload("resolve", root, name="../outside.md",
                         project_id=registered["data"]["project_id"],
                         idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"


def test_resolve_rejects_blank_name(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    result = run(payload("resolve", root, name="   ",
                         project_id=registered["data"]["project_id"],
                         idempotency_key="key-2"))
    assert result["error"]["code"] == "INVALID_PAYLOAD"


def test_resolve_rejects_escape_symlink(root: Path, tmp_path: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    outside = tmp_path / "outside.md"
    outside.write_text("外部内容", encoding="utf-8")
    link = root / "escape.md"
    os.symlink(outside, link)
    result = run(payload("resolve", root, name="escape.md",
                         project_id=registered["data"]["project_id"],
                         idempotency_key="key-2"))
    assert result["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert result["error"]["details"]["resolved_path"] == str(outside)


def test_resolve_allows_symlink_inside_root(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    target = root / "real.md"
    target.write_text("根内内容", encoding="utf-8")
    os.symlink(target, root / "alias.md")
    result = run(payload("resolve", root, name="alias.md",
                         project_id=registered["data"]["project_id"],
                         idempotency_key="key-2"))
    assert result["ok"] is True
    assert result["data"]["resolved_path"] == str(target)


def test_resolve_path_inside_root_succeeds(root: Path) -> None:
    registered = run(payload("register", root, name="长夜"))
    (root / "chapters").mkdir(parents=True)
    result = run(payload("resolve", root, name="chapters/第一章.md",
                         project_id=registered["data"]["project_id"],
                         idempotency_key="key-2"))
    assert result["ok"] is True
    assert result["data"]["resolved_path"] == str(root / "chapters" / "第一章.md")


def test_cross_project_records_invisible(tmp_path: Path) -> None:
    first_root = tmp_path / "book-a"
    second_root = tmp_path / "book-b"
    first = run(payload("register", first_root, name="甲书"))
    second = run(payload("register", second_root, name="乙书",
                         idempotency_key="key-2"))
    assert first["data"]["project_id"] != second["data"]["project_id"]

    leaked = run(payload("open", second_root,
                         project_id=first["data"]["project_id"],
                         idempotency_key="key-3"))
    assert leaked["error"]["code"] == "PROJECT_SCOPE_VIOLATION"
    assert leaked["error"]["details"]["registered_project_id"] == \
        second["data"]["project_id"]


def test_errors_are_single_class_with_code(root: Path) -> None:
    """每个模块一个异常类：实现层抛同一个类，薄壳映射成稳定错误码。"""
    with pytest.raises(ProjectRegistryError) as caught:
        命令._IMPL.register(payload("register", root, name="长夜", root_path="rel"))
    assert caught.value.code == "PROJECT_SCOPE_VIOLATION"
    assert caught.value.message
    assert caught.value.details["root_path"] == "rel"
