# V03 向量检索端（10-vector-retrieval）

## 启动条件
- 依赖：V02、S05。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现外部向量接收、查询编译、候选召回、排序、父子扩展和精确原文物化。

## 模块
- `vector_embedding_accept` → `tasks/vector_embedding_accept.yaml`
- `vector_query_compile` → `tasks/vector_query_compile.yaml`
- `vector_candidate_search` → `tasks/vector_candidate_search.yaml`
- `vector_rank` → `tasks/vector_rank.yaml`
- `vector_context_expand` → `tasks/vector_context_expand.yaml`
- `vector_materialize` → `tasks/vector_materialize.yaml`

## 完成判据
查询不机械经过文档chunker；短查询使用query模板；candidate_k/top_k/阈值/去重/排序通过；默认无跨项目、无过期版本；原文来自指定版本。

## 边界与禁令
召回、排序、扩展、物化必须分卡实现；不得把全部逻辑塞回一个检索模块。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
