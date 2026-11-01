# 写作 Harness MCP · 候选评判裁决

- 候选：modelcontextprotocol/python-sdk —— 结论：采用 —— 理由：官方MCP SDK直接覆盖服务端、客户端与两种必需传输，避免自造协议栈
- 候选：pydantic/pydantic —— 结论：采用 —— 理由：契约模型、输入校验与JSON Schema需要稳定的运行时基础
- 候选：modelcontextprotocol/inspector —— 结论：采用 —— 理由：官方调试工具可验证工具、资源、提示词与两种传输的契约一致性
- 候选：sqlite/sqlite —— 结论：采用 —— 理由：单机项目包需要事务、WAL和崩溃恢复，SQLite与本机共享文件夹边界匹配
- 候选：pytest-dev/pytest —— 结论：采用 —— 理由：现有门禁已经以pytest和覆盖率作为验收基础
