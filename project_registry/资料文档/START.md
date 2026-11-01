# project_registry · 接手入口

接手本模块的第一件事读本文件；它写明先读什么、当前阶段怎么判定、复现命令怎么写。

## 当前阶段

已实现并通过门禁，等待验收。模块内已有 `命令.py`、`实现/project_registry.py`、`tests/test_project_registry.py` 三份代码与本文档。

阶段判定：跑完成后判据那一节，末行是 `GATE PASS` 即「已过门禁」，是 `GATE FAIL` 即「未过」。

## 职责

登记一个项目数据根、返回稳定 `project_id`、并把之后所有路径读取限制在该根内。

本模块只做这一件事；稿件快照、状态机、记忆、向量都在别的模块，改它们不碰本目录。

## 读什么

1. `specs/2026-11-01-writing-harness-mcp.spec.md` 的「要求 R1：项目与数据隔离」——本模块的验收条款。
2. `specs/2026-11-01-writing-harness-mcp.interfaces.md` 第一节——入参键、返回键的单一事实源。
3. 本目录的 `实现/project_registry.py`——实现。
4. `tasks/project_registry.yaml` 的 `boundary`——本模块许可改动的文件清单。

## 结构

```text
project_registry/
├── 后端代码/
│   ├── 命令.py                    run 薄壳：校验入参 → 调实现 → 返回 envelope
│   ├── 实现/
│   │   └── project_registry.py    唯一职责：登记、打开、作用域强制、路径逃逸拒绝
│   └── tests/
│       └── test_project_registry.py  正常 / 失败 / 越权 36 条
├── 资料文档/
│   └── START.md                  本文件
└── 说明文件                       给人看的单页说明
```

## 接口

```text
接口：run(payload: dict) -> dict
├── 入参：request_id: str
├── 入参：project_id: str —— 登记时留空；打开/解析时填已登记身份
├── 入参：actor: dict —— actor_id、role、client_instance_id
├── 入参：idempotency_key: str
├── 入参：action: str —— register | open | resolve
├── 入参：root_path: str —— 数据根绝对路径
├── 入参：name: str —— register 是项目名；resolve 是根内相对路径
├── 返回：ok: bool
├── 返回：data: dict —— project_id、schema_version、data_root（resolve 另加 resolved_path）
└── 错误：ProjectRegistryError —— code 取下面错误码表
```

`data.data_root` 的键：`root_path`、`marker_path`、`status`、`name`、`registered_at`。

## 错误码

| code | 触发条件 |
|---|---|
| `PROJECT_SCOPE_VIOLATION` | 数据根为相对路径或含 `..`；项目内路径为绝对或含 `..`；真实路径落到根外；作用域与登记身份不符；resolve 时缺作用域 |
| `CONFLICT` | 同一数据根已登记为另一个项目名 |
| `IDEMPOTENCY_KEY_REUSE` | 同 actor、同 key、不同请求 |
| `PROJECT_NOT_REGISTERED` | 数据根没有登记档案 |
| `PROJECT_MARKER_CORRUPT` | 登记档案或幂等台账无法解析、字段缺失 |
| `PROJECT_STORE_IO_ERROR` | 登记档案读不了或写不了 |
| `INVALID_PAYLOAD` | 必填字段缺失或类型不对、`name` 为空 |

## 规则

- 登记档案落在 `<root>/.writing-harness/project.json`，幂等台账落在同目录 `idempotency.json`；两份都先写临时文件再原子替换，半途失败不留半个档案。
- 同一数据根同名再登记返回既有身份，不新建项目；换名字则判 `CONFLICT`——这正是 R1「同一数据根不能登记为两个项目」的执行方式。
- 所有入参路径先 `realpath` 再比较是否落在根内：目录穿越与根外符号链接在规范化之后自然暴露，一律拒绝。
- 根内符号链接放行：解析后仍在根内就合法。
- 跨项目不可见：带别的项目身份打开，只返回 `PROJECT_SCOPE_VIOLATION`，不返回任何对方记录。

## 复现

环境（在仓库根跑，一条命令建成）：

```bash
python3 -m venv .venv && .venv/bin/python -m pip install pytest pytest-cov pyyaml
```

只跑本模块测试：

```bash
cd project_registry && ../.venv/bin/python -m pytest 后端代码/tests -q
```

完成判据（在仓库根跑）：

```bash
.venv/bin/python .agents/gate.py project_registry/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

末行必须是 `GATE PASS`。当前实测：`GATE PASS`，覆盖率 98.1%。

手动冒烟（在仓库根跑，`$root` 换成自己的临时目录）：

```bash
.venv/bin/python - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "project_registry/后端代码")
from 命令 import run

root = Path("/tmp/wh-smoke") / "book"
base = {"request_id": "r1", "project_id": "", "idempotency_key": "k1",
        "actor": {"actor_id": "human-1", "role": "human",
                  "client_instance_id": "c1"},
        "root_path": str(root), "name": "长夜"}
print(run({**base, "action": "register"})["data"]["project_id"])
PY
```

## 常见改错

- 在 `命令.py` 里写业务判断：薄壳只校验入参与分发，规则留 `实现/`。
- 新增异常类：本模块只认 `ProjectRegistryError`，按 `code` 区分子类。
- 用 `os.path.exists` 代替 `realpath` 判断越界：符号链接会漏网。
- 把幂等台账塞进 SQLite：本模块不建库，数据库是 `sqlite_migration` 的职责。
