# spec loop

specs/ 下为当前功能建一套文档，命名 <日期>-<短名>：

specs/
├── <日期>-<短名>.dialogue.md  ← 对话文档
├── <日期>-<短名>.spec.md      ← spec 文档
└── <日期>-<短名>.verdict.md   ← 评判裁决

## 对话文档

用户一句、AI 一句，当轮逐句追加原话，一字不补、一字不删；上下文被压缩或丢失时，从它恢复历史。

讨论模块时按批次记，每批条数的上下限见 `.agents/source_gate.py` 的 `MIN_BATCH` / `MAX_BATCH`；末批是「剩多少发多少」的那批，可以不足下限：

```
【模块批次 <编号>】
- <模块名> —— 判定：<保留|不要|改造|自造> —— 理由：<一句话>
```

完成判据：每批不超过上限，非末批不少于下限；每个模块带判定与理由；**讨论过的每个模块都在 `tasks/` 里有卡**——这条由 `.agents/source_gate_delivery.py` 的 B5 对账机械核。

## spec 文档

AI 对当前功能的整理，随每轮讨论更新；首轮回复给出地址：specs/<日期>-<短名>.spec.md（相对路径）。

### 原话

用户描述原文，一字不改。

### 成熟的项目

需求反推与 Spec 复核两次检索到的候选全部写在这里。门禁实时核对 star（允许漂移容差，见 `.agents/source_gate.py` 的 `STAR_TOLERANCE`），并按下载地址取回快照核对 pin、下载物与 extract 行区间；`updated` / `release` 只核对「不是未来日期」：

```yaml
- repo: <owner>/<repo>
  star: <整数>
  updated: <YYYY-MM-DD>
  release: <tag>@<YYYY-MM-DD>
  lang: <Python|Rust|PHP|...>
  pin: <40 位提交 sha>
  url: https://github.com/<owner>/<repo>/archive/<pin>.tar.gz
  extract: <上游路径:行区间>
  verdict: <采用|不采用>
  reason: <一句话>
```

star 硬门槛与漂移容差、排序月数、理由词表的数值全在 `.agents/source_gate.py` 里。
完成判据：`.venv/bin/python .agents/gate.py --spec <spec 路径>` 打印 `SOURCE OK`。

### 要求

每条要求按以下格式：

```
要求 <编号>：<名称>
├── 要求陈述：<主体>必须<具体能力>
└── 场景 <名称>（可多条）
    ├── 当：初始状态与触发动作
    └── 则：预期结果
```

### 接口

```
接口：run(payload: dict) -> dict
├── 入参：<键名>: <类型> —— <含义>
├── 返回：<键名>: <类型> —— <含义>
└── 错误：<异常类名> —— <触发条件>（迁移后是 thiserror 枚举变体）
```

类型写 Python 类型名（int / float / str / bool / list[...] / dict），迁移时直接换成 Rust 类型。

## 评判裁决

候选合并后交评判子代理，逐条对照要求比出哪个更符合需求；提示词是 `.agents/adjudicate.md`。

```
- 候选：<owner>/<repo> —— 结论：<采用|不采用> —— 理由：<一句话>
```

完成判据：每条候选都在，且结论只用采用 / 不采用——结构由 `.agents/source_gate_delivery.py` 的 B4 机械核。

## 功能完成

整套文档移入 specs/archive/；开下一个功能，建新一套。

结构化的说明用树状图表达。
