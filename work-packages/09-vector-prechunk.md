# V02 向量预切分端（09-vector-prechunk）

## 启动条件
- 依赖：V01。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现来源绑定、归一化offset、语义父子切分、稳定chunk_id和profile守卫。

## 模块
- `vector_source_bind` → `tasks/vector_source_bind.yaml`
- `vector_normalize` → `tasks/vector_normalize.yaml`
- `vector_chunk` → `tasks/vector_chunk.yaml`
- `vector_chunk_id` → `tasks/vector_chunk_id.yaml`
- `vector_profile_guard` → `tasks/vector_profile_guard.yaml`

## 完成判据
原文映射100%正确；同配置重建ID一致；配置变化生成新兼容键；不兼容索引写入前拒绝。

## 边界与禁令
切分按章节/场景/段落/句子优先；不得只用固定token滑窗。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
