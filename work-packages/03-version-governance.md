# S03 版本治理与人类锁（03-version-governance）

## 启动条件
- 依赖：S02。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现diff、血缘、回滚、事件追加读取和人类锁。

## 模块
- `artifact_diff` → `tasks/artifact_diff.yaml`
- `lineage_trace` → `tasks/lineage_trace.yaml`
- `rollback_commit` → `tasks/rollback_commit.yaml`
- `event_append` → `tasks/event_append.yaml`
- `event_read` → `tasks/event_read.yaml`
- `human_lock` → `tasks/human_lock.yaml`

## 完成判据
回滚生成新版本且不删历史；旧批准失效；AI持锁写入拒绝；事件顺序和来源可追溯。

## 边界与禁令
回滚只能在人工决策下执行；不得用删除历史实现回滚。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
