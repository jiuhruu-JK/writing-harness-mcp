# V01 向量契约符合性（08-vector-contract）

## 启动条件
- 依赖：S00、S01、S02。
- 先读 `docs/START.md`、主 spec、接口总表、向量契约和本包涉及的任务卡。

## 目标
冻结14个向量叶子模块的schema、错误、兼容矩阵、golden fixtures和测试替身契约。

## 模块
- 本包不新增叶子模块。

## 完成判据
每个向量模块有完整run契约与验收场景；不兼容配置、跨项目、旧版本、删除、重建、外部向量错误均被测试；无后端时明确报不可用。

## 边界与禁令
本包不要求生产ANN索引，不内置embedding模型；不得改变角色ContextItem结构。

## 门禁
每张任务卡单独实现、单独测试。交下一张卡前必须通过：

```bash
.venv/bin/python .agents/gate.py <模块名>/ --spec specs/2026-11-01-writing-harness-mcp.spec.md
```

最后一行必须是 `GATE PASS`。整包完成后按依赖顺序交给下一包。
