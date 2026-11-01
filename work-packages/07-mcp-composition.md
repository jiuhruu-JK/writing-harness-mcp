# S06b MCP组合与传输（07-mcp-composition）

## 启动条件
- 依赖：S06a、S04。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现角色会话路由、工具和提示词注册、stdio与Streamable HTTP传输。

## 模块
- `mcp_server` → `tasks/mcp_server.yaml`
- `mcp_stdio_transport` → `tasks/mcp_stdio_transport.yaml`
- `mcp_http_transport` → `tasks/mcp_http_transport.yaml`

## 完成判据
业务层不感知传输；会话只暴露本角色工具；两种传输跑同一契约套件；断线不转移租约。

## 边界与禁令
mcp_server不拥有业务schema/prompt；HTTP默认仅loopback；真实客户端只有实测才登记。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
