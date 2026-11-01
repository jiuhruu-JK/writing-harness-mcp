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
│       └── test_sqlite_migration.py  正常 / 失败 / 越权 46 条
├── 资料文档/
│   └── START.md                  本文件
└── 说明文件                       给人看的单页说明
```

## 接口

```text
接口：run(payload: dict) -> dict
├── 入参：request_id: str
├── 入参：project_id: str —— 项目作用域，必填；台账按项目隔离
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
| `PROJECT_SCOPE_VIOLATION` | 路径为相对或含 `..`；迁移文件真实路径落到迁移根之外；缺项目作用域；库里已有别家项目的迁移记录 |
| `IDEMPOTENCY_KEY_REUSE` | 同 actor、同 key、不同请求 |
| `INVALID_PAYLOAD` | 必填字段缺失、类型不对、路径非绝对 |

## 规则

- 台账自己建两张表：`schema_migrations`（按 `(project_id, version)` 记录已执行版本）与 `migration_requests`（幂等请求）。这两张表由本模块负责，不算业务表。
- 一次 `run` 就是**一个** `BEGIN IMMEDIATE` 事务：幂等校验、建台账、逐条执行迁移、「只建声明表」校验、写幂等结果全在同一事务里。任何一步失败整体回滚，库里一张表都不留——半途失败不留半张表。
- 项目隔离：`project_id` 必填；台账每行带 `project_id`，只读本项目记录。库里若已有别家项目的迁移记录，直接 `PROJECT_SCOPE_VIOLATION`，读不到也写不进。
- 幂等：同 actor、同 key、同请求返回首次结果；同 key 换请求内容判 `IDEMPOTENCY_KEY_REUSE`。幂等读写在事务内，多线程同键并发时排队等锁，全部拿到首次结果。
- 并发：连接用 `busy_timeout=10s`；并发首建同一个库、切换 WAL 需要独占锁，失败时按 20 次 × 50ms 重试，不把同伴顶掉。
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

末行必须是 `GATE PASS`。当前实测：`GATE PASS`，覆盖率 96.7%。

手动冒烟（在仓库根跑）：

```bash
.venv/bin/python - <<'PY'
import importlib.util, sqlite3, sys, tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "wh_cmd", "sqlite_migration/后端代码/命令.py")
命令 = importlib.util.module_from_spec(spec)
sys.modules["wh_cmd"] = 命令
spec.loader.exec_module(命令)
run = 命令.run

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

入口按文件路径装载；不要用 `sys.path.insert` + `from 命令 import run`——每个模块入口都叫 `命令.py`，同进程里会互相顶替。

## 常见改错

- 在 `命令.py` 里建表或排序迁移：薄壳只校验入参与分发。
- 逐个迁移各开事务：第 2 个失败会留下第 1 个已提交的迁移，库里就出现「台账记了一条、文件其实没跑完」的错位。整次调用必须一个事务。
- 用 `text.split(";")` 切语句：字符串和注释里的分号会切断语句。
- 在迁移文件里建业务表但不写 `-- tables:` 头：被判「建了未声明的表」。
