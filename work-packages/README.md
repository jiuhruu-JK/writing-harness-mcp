# 实施工作包

这些工作包只规定交付顺序、模块集合与验收，不包含实现代码。所有任务卡位于 `tasks/`，规范入口见 `docs/START.md`。

| 包 | 标题 | 依赖 | 模块数 |
|---|---|---|---|
| [00-contracts](00-contracts.md) | S00 总契约 | 无 | 0 |
| [01-foundation](01-foundation.md) | S01 项目与迁移基础 | S00 | 2 |
| [02-artifacts](02-artifacts.md) | S02 不可变快照与精确读取 | S01 | 2 |
| [03-version-governance](03-version-governance.md) | S03 版本治理与人类锁 | S02 | 6 |
| [04-workflow-and-human](04-workflow-and-human.md) | S04 13阶段、串并行与人类提交 | S02、S03 | 22 |
| [05-memory](05-memory.md) | S05 项目记忆与总记忆 | S02、S03 | 5 |
| [06-ai-roles](06-ai-roles.md) | S06a 七角色隔离 | S04（上下文数据结构可用S00契约） | 28 |
| [07-mcp-composition](07-mcp-composition.md) | S06b MCP组合与传输 | S06a、S04 | 3 |
| [08-vector-contract](08-vector-contract.md) | V01 向量契约符合性 | S00、S01、S02 | 0 |
| [09-vector-prechunk](09-vector-prechunk.md) | V02 向量预切分端 | V01 | 5 |
| [10-vector-retrieval](10-vector-retrieval.md) | V03 向量检索端 | V02、S05 | 6 |
| [11-vector-governance](11-vector-governance.md) | V04 向量治理与质量 | V03 | 3 |
