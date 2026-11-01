# S04 13阶段、串并行与人类提交（04-workflow-and-human）

## 启动条件
- 依赖：S02、S03。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
实现主线迁移、并行汇合、全部stage门禁及人类/外部提交工具。

## 模块
- `workflow_transition` → `tasks/workflow_transition.yaml`
- `workflow_parallel_join` → `tasks/workflow_parallel_join.yaml`
- `stage_outline_big_payoff` → `tasks/stage_outline_big_payoff.yaml`
- `stage_ai_draft` → `tasks/stage_ai_draft.yaml`
- `stage_serial_logic_review` → `tasks/stage_serial_logic_review.yaml`
- `stage_style_candidates` → `tasks/stage_style_candidates.yaml`
- `stage_logic_correction` → `tasks/stage_logic_correction.yaml`
- `stage_small_payoff` → `tasks/stage_small_payoff.yaml`
- `stage_fatigue_review` → `tasks/stage_fatigue_review.yaml`
- `stage_human_voice` → `tasks/stage_human_voice.yaml`
- `stage_conservative_cleanup` → `tasks/stage_conservative_cleanup.yaml`
- `stage_human_polish` → `tasks/stage_human_polish.yaml`
- `stage_tts` → `tasks/stage_tts.yaml`
- `stage_human_listening` → `tasks/stage_human_listening.yaml`
- `stage_delivery` → `tasks/stage_delivery.yaml`
- `stage_reflow` → `tasks/stage_reflow.yaml`
- `outline_approval_tool` → `tasks/outline_approval_tool.yaml`
- `voice_reconstruction_tool` → `tasks/voice_reconstruction_tool.yaml`
- `human_polish_tool` → `tasks/human_polish_tool.yaml`
- `listening_fix_tool` → `tasks/listening_fix_tool.yaml`
- `delivery_finalize_tool` → `tasks/delivery_finalize_tool.yaml`
- `tts_artifact_tool` → `tasks/tts_artifact_tool.yaml`

## 完成判据
非法跳转和错误角色拒绝；③串行；④候选并行后串行校正；⑤与⑥独立；人工阶段不可由AI代交。

## 边界与禁令
stage卡只负责阶段门禁；提交工具只负责对应人工/外部输入，不得互相吞并职责。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
