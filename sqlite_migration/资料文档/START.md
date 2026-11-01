# sqlite_migration · 接手入口

接手本模块的第一件事读本文件；它写明先读什么、当前阶段怎么判定、复现命令怎么写。

## 当前阶段

已实现并通过门禁，等待验收。模块内已有 `命令.py`、`实现/sqlite_migration.py`、`tests/test_sqlite_migration.py`。

阶段判定：跑完成后判据那一节，末行是 `GATE PASS` 即「已过门禁」，是 `GATE FAIL` 即「未过」。

## 职责

按声明顺序执行各叶子模块自有的 SQLite 迁移：重复执行幂等、只建声明表、顺序冲突与半途失败回滚。

本模块只做这一件事；它不定义任何业务表，业务表由各叶子模块自己的迁移文件声明。

## 读什么

1. `specs/2026-11-01-writing-harness-mcp.spec.md` 的「要求 R1：项目与数据隔离」「要求 R14：可靠提交与恢复」。
2. `specs/2026-11-01-writing-harness-mcp.interfaces.md` 第一节——入参键、返回键的单一事实源。
3. 本目录的 `实现/sqlite_migration.py`——实现。
4. `tasks/sqlite_migration.yaml` 的 `boundary`——本模块许可改动的文件清单。

## 结构

```text
sqlite_migration/
├── 后端代码/
│   ├── 命令.py                    run 薄壳：校验入参 → 调实现 → 返回 envelope
│   ├── 实现/
│   │   └── sqlite_migration.py    唯一职责：读迁移声明、顺序执行、事务回滚、幂等台账
│   └── tests/
│       └── test_sqlite_migration.py  正常 / 失败 / 越权 35 条
├── 资料文档/
│   └── START.md                  本文件
└── 说明文件                       给人看的单页说明
```

## 接口

```text
接口：run(payload: dict) -> dict
├── 入参：request_id: str
├── 入参：project_id: str
├── 入参：actor: dict —— actor_id、role、client_instance_id
├── 入参：idempotency_key: str
├── 入参：database_path: str —— 库文件绝对路径
├── 入参：migrations_root: str —— 迁移根绝对路径
├── 返回：ok: bool
├── 返回：data: dict —— applied_versions（已执行版本号列表）、current_version（最新版本号，无迁移为 0）
└── 错误：SqliteMigrationError —— code 取下面错误码表
```

## 迁移文件怎么声明

```text
<migrations_root>/<模块名>/<顺序号>_<名字>.sql
```

- 执行顺序 = 模块名升序 + 顺序号升序；同一模块的顺序号必须从 1 起连续。
- 文件头用 `-- tables: a, b` 声明本文件创建的表，多个表名逗号分隔。
- 没有 `-- tables:` 头就是「一张表都不建」；建了未声明的表判失败。

## 错误码

| code | 触发条件 |
|---|---|
| `MIGRATION_ORDER_CONFLICT` | 同一模块顺序号不连续；新迁移排到已执行迁移之前；已执行数多于声明数 |
| `CONFLICT` | 已执行迁移的文件内容被改动（checksum 不符） |
| `MIGRATION_FAILED` | 语句执行失败；文件名不合规；建了未声明表；声明为空；末尾有不完整语句；库打不开 |
| `MIGRATIONS_ROOT_MISSING` | 迁移根不是目录 |
| `MIGRATION_MODULE_MISSING` | 迁移模块目录里一个 `.sql` 都没有 |
| `PROJECT_SCOPE_VIOLATION` | 路径为相对或含 `..`；迁移文件真实路径落到迁移根之外 |
| `IDEMPOTENCY_KEY_REUSE` | 同 actor、同 key、不同请求 |
| `INVALID_PAYLOAD` | 必填字段缺失、类型不对、路径非绝对 |

## 规则

- 台账自己建两张表：`schema_migrations`（已执行版本）与 `migration_requests`（幂等请求）。这两张表由本模块负责，不算业务表。
- 每个迁移各开一个 `BEGIN IMMEDIATE` 事务：语句与版本记录同进同退。第 2 个迁移失败，第 1 个已执行的保留，失败的那个整体回滚——不留半张表。
- 幂等：同 actor、同 key、同请求返回首次结果；同 key 换请求内容判 `IDEMPOTENCY_KEY_REUSE`。
- 语句按完整语句切分，用 `sqlite3.complete_statement` 逐字符判断边界：字符串与注释里的分号不算分隔，同一行写两条语句也能拆开。最后一条语句后的整行注释不算残留语句。
- 已执行的迁移文件内容被改动即判 `CONFLICT`：历史迁移不可改写，改行为就加新文件。

## 复现

环境（在仓库根跑，一条命令建成）：

```bash
python3 -m venv .venv && .venv/bin/python -m pip install pytest pytest-cov pyyaml
```

只跑本模块测试：

```bash
cd sqlite_migration && ../.venv/bin/python -m pytest 后端代码/tests -q
```

完成判据（在仓库根跑）：

```bash
.venv/bin/python .agents/gate.py sqlite_migration/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

末行必须是 `GATE PASS`。当前实测：`GATE PASS`，覆盖率 97.7%。

手动冒烟（在仓库根跑）：

```bash
.venv/bin/python - <<'PY'
import sqlite3, sys, tempfile
from pathlib import Path
sys.path.insert(0, "sqlite_migration/后端代码")
from 命令 import run

tmp = Path(tempfile.mkdtemp())
db, mig = tmp / "state.db", tmp / "migrations"
(mig / "alpha").mkdir(parents=True)
(mig / "alpha" / "1_create_documents.sql").write_text(
    "-- tables: documents\n"
    "CREATE TABLE documents (id INTEGER PRIMARY KEY, body TEXT);\n",
    encoding="utf-8")
base = {"request_id": "r1", "project_id": "proj-1", "idempotency_key": "k1",
        "actor": {"actor_id": "migrator", "role": "system",
                  "client_instance_id": "c1"},
        "database_path": str(db), "migrations_root": str(mig)}
first = run(base)
print(first["data"])                     # {'applied_versions': [1], 'current_version': 1}
print(run({**base, "idempotency_key": "k2"})["data"])   # 同上，幂等
print(sorted(r[0] for r in sqlite3.connect(str(db)).execute(
    "SELECT name FROM sqlite_master WHERE type='table'")))
PY
```

## 常见改错

- 在 `命令.py` 里建表或排序迁移：薄壳只校验入参与分发。
- 一次事务跑完全部迁移：第 2 个失败会把第 1 个也回滚，违反「失败只回滚该迁移」。
- 用 `text.split(";")` 切语句：字符串和注释里的分号会切断语句。
- 在迁移文件里建业务表但不写 `-- tables:` 头：被判「建了未声明的表」。
