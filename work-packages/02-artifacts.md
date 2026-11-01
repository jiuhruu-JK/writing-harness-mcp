# S02 不可变快照与精确读取（02-artifacts）

## 启动条件
- 依赖：S01。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现内容快照提交、哈希、当前指针、journal和精确历史读取。

## 模块
- `artifact_commit` → `tasks/artifact_commit.yaml`
- `artifact_resolve` → `tasks/artifact_resolve.yaml`

## 完成判据
提交失败不改变head；镜像可按journal恢复；历史读取不受后续修改影响；哈希/版本不符拒绝。

## 边界与禁令
完成提交路径后再做读取路径；外部编辑冲突留在S03处理。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
