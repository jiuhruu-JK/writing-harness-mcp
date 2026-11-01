# 写作 Harness MCP

开源写作 Harness 的 MCP 服务：不同写作 Agent 通过同一个 MCP 和同一项目文件夹接力，共享稿件状态、版本、人工裁决与分层记忆。

**当前仓库状态：规格与实施工作包已完成，MCP 实现代码尚未开始。**

## 远端

- 仓库：<https://github.com/jiuhruu-JK/writing-harness-mcp>
- 分支：`main`
- 下一实现 AI 必须从远端 clone 后工作，不以任何单机目录为交接真相。

## 接手入口

阅读顺序固定：

1. [接手说明](docs/START.md)
2. [S00 总契约](specs/2026-11-01-writing-harness-mcp.spec.md)
3. [接口总表](specs/2026-11-01-writing-harness-mcp.interfaces.md)
4. [向量契约](specs/2026-11-01-writing-harness-mcp.vector.md)
5. [工作包索引](work-packages/README.md)

第一个实现工作包是 [01-foundation](work-packages/01-foundation.md)。

## 分工

- 规划 AI：只写 Spec、任务卡、工作包与交接文档，不写 MCP 实现。
- 实现 AI：按任务卡逐模块实现、测试、过门禁、提交并推送。
- 人类：所有大爽点、最终审美、跨项目记忆晋升和策略变更由人裁决。

## 目录

```text
.agents/        现有研发流程与门禁
docs/           接手说明
specs/          S00 总契约、接口、向量契约、对话与裁决
tasks/          82张叶子模块任务卡
work-packages/  按依赖排序的实施包
```

## 验收

每个模块必须单独过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。工作包总体验收见各包文档。
