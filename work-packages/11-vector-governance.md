# V04 向量治理与质量（11-vector-governance）

## 启动条件
- 依赖：V03。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现索引代际重建、幂等删除和固定golden集质量门禁。

## 模块
- `vector_index_rebuild` → `tasks/vector_index_rebuild.yaml`
- `vector_index_delete` → `tasks/vector_index_delete.yaml`
- `vector_quality_eval` → `tasks/vector_quality_eval.yaml`

## 完成判据
重建期间旧代际可读并原子切换；删除不复活；Recall@10、原文准确率、污染和配置拒绝达标。

## 边界与禁令
质量不达标必须失败并报告全部profile、索引代际与golden集版本。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
