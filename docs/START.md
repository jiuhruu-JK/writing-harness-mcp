# START · 下一实现 AI 的唯一入口

## 当前状态

- 阶段：S00 总契约与工作包完成，等待 S01 实现。
- 规划 AI 未写任何 MCP 实现代码。
- 所有交接内容以远端 `main` 为准。
- 仓库：`https://github.com/jiuhruu-JK/writing-harness-mcp`

## 第一件事

```bash
git clone https://github.com/jiuhruu-JK/writing-harness-mcp.git
cd writing-harness-mcp
```

然后按顺序阅读：

1. `AGENTS.md`
2. `specs/2026-11-01-writing-harness-mcp.spec.md`
3. `specs/2026-11-01-writing-harness-mcp.interfaces.md`
4. `specs/2026-11-01-writing-harness-mcp.vector.md`
5. `work-packages/01-foundation.md`
6. `tasks/project_registry.yaml`
7. `tasks/sqlite_migration.yaml`

## 现在允许做的事

只实现 [01-foundation](../work-packages/01-foundation.md) 中的两个叶子模块：

- `project_registry`
- `sqlite_migration`

每个模块一张任务卡；一次只做一个模块。做完一个，测试、过门禁、提交、推送，再开始下一张卡。

## 禁止做的事

- 不改写S00总契约、接口总表、向量契约。
- 不把多个叶子模块合成大模块。
- 不创建共享review工具或共享prompt。
- 不实现小爽点/疲劳自动模式。
- 不接入生产向量后端。
- 不让MCP调用写作、审核、embedding或TTS模型。
- 不让AI裁决大爽点或最终审美。
- 不把作者定稿导入外部修辞库。
- 不把原始日志直接塞进正式检索。
- 不在没有人工晋升记录时写跨项目总记忆。
- 不擅自更改AGPL-3.0许可证。

## 环境

当前开发机是Windows；在Git Bash中：

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install pytest pytest-cov pyyaml
```

Linux/macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pytest pytest-cov pyyaml
```

## 单模块完成判据

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

Windows使用：

```bash
.venv/Scripts/python.exe .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

必须满足：

1. 最后一行是 `GATE PASS`；
2. 任务卡 `boundary` 外零改动；
3. 同步测试覆盖正常、失败和越权路径；
4. 更新该模块的 `资料文档/START.md` 与 `说明文件`；
5. commit message 首行使用任务卡的施工说明；
6. 推送远端后才算完成。

## 下一个工作包

`01-foundation` 全部通过后，按 [工作包索引](../work-packages/README.md) 进入 `02-artifacts`，不提前跨包。
