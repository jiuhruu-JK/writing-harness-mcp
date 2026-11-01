# S05 项目记忆与总记忆（05-memory）

## 启动条件
- 依赖：S02、S03。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现记忆候选、人工整理、作用域守卫、人工晋升和外部修辞导入。

## 模块
- `memory_candidate` → `tasks/memory_candidate.yaml`
- `memory_curation` → `tasks/memory_curation.yaml`
- `memory_scope_guard` → `tasks/memory_scope_guard.yaml`
- `memory_promotion` → `tasks/memory_promotion.yaml`
- `rhetoric_external_import` → `tasks/rhetoric_external_import.yaml`

## 完成判据
原始日志默认不可检索；项目A看不到项目B；无人工决策不能晋升；作者定稿不能进修辞库。

## 边界与禁令
跨项目共享唯一路径是候选→人工确认→总记忆副本→保留血缘。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
