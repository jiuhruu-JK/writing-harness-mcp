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
│       └── test_sqlite_migration.py  正常 / 失败 / 越权 61 条
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
- 「只建声明表」按**本次执行的差集**判：只比对「执行后新增的表」与「本次声明的表」，库里原有表（别家模块建的）不算越界。多模块共用一个状态库是常态，本模块只对自己本次执行负责。

## 错误码

| code | 触发条件 |
|---|---|
| `MIGRATION_ORDER_CONFLICT` | 同一模块顺序号不连续；新迁移排到已执行迁移之前；已执行数多于声明数 |
| `CONFLICT` | 已执行迁移的文件内容被改动（checksum 不符） |
| `MIGRATION_FAILED` | 语句执行失败；文件名不合规；建了未声明表；`-- tables:` 声明为空；末尾有不完整语句；迁移文件自带 `BEGIN`/`COMMIT` 等事务控制语句；库打不开 |
| `MIGRATIONS_ROOT_MISSING` | 迁移根不是目录 |
| `PROJECT_SCOPE_VIOLATION` | 路径为相对或含 `..`；迁移文件真实路径落到迁移根之外；缺项目作用域；库已归别家项目独占（`migration_project` 绑定，含绑定缺失时按已执行迁移回推的归属） |
| `IDEMPOTENCY_KEY_REUSE` | 同 actor、同 key、不同请求 |
| `INVALID_PAYLOAD` | 必填字段缺失、类型不对、路径非绝对 |

## 规则

- 台账自己建三张表：`migration_project`（库的项目归属，单行）、`schema_migrations`（按 `(project_id, version)` 记录已执行版本）与 `migration_requests`（按 `(project_id, actor_id, key)` 记幂等请求）。这三张表由本模块负责，不算业务表。
- 一次 `run` 就是**一个** `BEGIN IMMEDIATE` 事务：幂等校验、建台账、逐条执行迁移、「只建声明表」校验、写幂等结果全在同一事务里。任何一步失败整体回滚，库里一张表都不留——半途失败不留半张表。
- 项目隔离：`project_id` 必填；台账每行带 `project_id`，只读本项目记录。整个库归**第一个用它的项目**独占：确认归属后一律补写 `migration_project`（`INSERT OR IGNORE`），之后别家项目再用同一个库一律 `PROJECT_SCOPE_VIOLATION`——零迁移的首跑也会落绑定，不存在「空台账放行」的空档。绑定表缺失时（旧库，或运维清表）按 `schema_migrations` 的既有行回推归属，回推确认后同样补写绑定，因此独占不依赖台账一直在。项目归属校验排在幂等重放之前：换项目的请求先撞作用域，不会先拿到别人记下的结果。
- 幂等：同 actor、同 key、同请求返回首次结果；同 key 换请求内容判 `IDEMPOTENCY_KEY_REUSE`。幂等读写在事务内，多线程同键并发时排队等锁，全部拿到首次结果。
- 并发：连接用 `busy_timeout=10s`；并发首建同一个库、切换 WAL 需要独占锁，失败时按 20 次 × 50ms 重试，不把同伴顶掉。
- 旧库升级：`migration_requests` 若缺 `project_id` 列（早期版本的库），就地 `DROP` 后按新结构重建。**旧幂等行不搬运、直接丢弃**——旧表没有项目列，搬不出项目归属，所以升级后同一个键重试会重跑一次、不复现首次结果；已执行的迁移记录（`schema_migrations`）原样保留，不会重跑迁移。这段重建在同一个事务里，后续任何一步失败会连同重建一起回滚，旧结构原封不动。
- 语句按完整语句切分，用 `sqlite3.complete_statement` 逐字符判断边界：字符串与注释里的分号不算分隔，同一行写两条语句也能拆开。最后一条语句后的整行注释不算残留语句。
- 迁移文件不得自带 `BEGIN`/`COMMIT`/`ROLLBACK`/`SAVEPOINT` 等事务控制语句：整次调用已在一个事务里，自带事务会把它撑破，出现 `cannot start a transaction within a transaction`；这类文件在切分阶段就判不合规，不执行。
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

末行必须是 `GATE PASS`。当前实测：`GATE PASS`，覆盖率 ≥96.8%（多次实跑 96.8–98.1%，并发用例的线程交错会影响分支覆盖）。

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
