# S06a 七角色隔离（06-ai-roles）

## 启动条件
- 依赖：S04（上下文数据结构可用S00契约）。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现七个AI角色各自独立的取任务、交结果、上下文和提示词模块。

## 模块
- `draft_assignment_tool` → `tasks/draft_assignment_tool.yaml`
- `draft_submission_tool` → `tasks/draft_submission_tool.yaml`
- `draft_context` → `tasks/draft_context.yaml`
- `draft_prompt` → `tasks/draft_prompt.yaml`
- `logic_review_assignment_tool` → `tasks/logic_review_assignment_tool.yaml`
- `logic_review_submission_tool` → `tasks/logic_review_submission_tool.yaml`
- `logic_review_context` → `tasks/logic_review_context.yaml`
- `logic_review_prompt` → `tasks/logic_review_prompt.yaml`
- `style_imitation_assignment_tool` → `tasks/style_imitation_assignment_tool.yaml`
- `style_imitation_submission_tool` → `tasks/style_imitation_submission_tool.yaml`
- `style_imitation_context` → `tasks/style_imitation_context.yaml`
- `style_imitation_prompt` → `tasks/style_imitation_prompt.yaml`
- `logic_correction_assignment_tool` → `tasks/logic_correction_assignment_tool.yaml`
- `logic_correction_submission_tool` → `tasks/logic_correction_submission_tool.yaml`
- `logic_correction_context` → `tasks/logic_correction_context.yaml`
- `logic_correction_prompt` → `tasks/logic_correction_prompt.yaml`
- `small_payoff_assignment_tool` → `tasks/small_payoff_assignment_tool.yaml`
- `small_payoff_submission_tool` → `tasks/small_payoff_submission_tool.yaml`
- `small_payoff_context` → `tasks/small_payoff_context.yaml`
- `small_payoff_prompt` → `tasks/small_payoff_prompt.yaml`
- `fatigue_review_assignment_tool` → `tasks/fatigue_review_assignment_tool.yaml`
- `fatigue_review_submission_tool` → `tasks/fatigue_review_submission_tool.yaml`
- `fatigue_review_context` → `tasks/fatigue_review_context.yaml`
- `fatigue_review_prompt` → `tasks/fatigue_review_prompt.yaml`
- `conservative_cleanup_assignment_tool` → `tasks/conservative_cleanup_assignment_tool.yaml`
- `conservative_cleanup_submission_tool` → `tasks/conservative_cleanup_submission_tool.yaml`
- `conservative_cleanup_context` → `tasks/conservative_cleanup_context.yaml`
- `conservative_cleanup_prompt` → `tasks/conservative_cleanup_prompt.yaml`

## 完成判据
每角色只发现自己工具/提示词；角色上下文越权拒绝；修改一个prompt不影响其他角色文件、schema和快照。

## 边界与禁令
不得创建共享review schema或总prompt模块；文风候选与逻辑校正保持不同角色。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
