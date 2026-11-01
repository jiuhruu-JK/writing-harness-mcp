# S01 项目与迁移基础（01-foundation）

## 启动条件
- 依赖：S00。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现项目身份、数据根隔离和模块自有迁移执行。

## 模块
- `project_registry` → `tasks/project_registry.yaml`
- `sqlite_migration` → `tasks/sqlite_migration.yaml`

## 完成判据
同一数据根不可重复登记；目录穿越和根外符号链接拒绝；迁移幂等、顺序失败回滚。

## 边界与禁令
先完成两张卡，再跑各自模块门禁；不得提前创建其他业务表。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
