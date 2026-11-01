# 写作 Harness MCP · 向量契约（规范附件）

本文件冻结预切分端与检索端的对齐标准。MVP必须实现本文件定义的schema、兼容性矩阵和golden fixtures；生产向量后端可后接，但不得改变角色工具或`ContextItem`结构。

## 1. 权威来源

每个索引进项先建立`SourceRef`：

| 字段 | 约束 |
|---|---|
| `project_id` | 来源项目；总记忆副本也保留原项目 |
| `source_artifact_id` | 稳定稿件或外部资料身份 |
| `source_version` | 明确的不可变版本，不复用 |
| `source_hash` | 权威快照规范字节的SHA-256 |
| `source_kind` | 稿件、项目记忆、总记忆、外部修辞范本等 |
| `scope` | `project`或`global` |
| `media_type` | 权威产物的媒体类型 |
| `supersedes` | 前一版本，可为空 |

- 权威快照是内容来源；SQLite保存身份、版本和索引元数据。
- 可读Markdown镜像不是默认检索权威，避免镜像重生成造成chunk与原文错位。
- 外部范本先登记为外部artifact；作者定稿不得进入外部修辞库。

## 2. 归一化与offset映射

首版规则固定为：Unicode NFC、换行统一为LF。禁止lowercase、空白折叠、标点改写、Markdown清洗和语义删减。

任何有损变换必须升级`normalizer_profile_version`并建立新索引，不得静默替换。

持久化：

- 权威快照原文；
- 归一化文本；
- normalizer配置版本；
- `offset_map`。

范围统一使用半开UTF-8字节区间`[start,end)`。`offset_map`必须能处理多字节字符、组合字符、换行转换以及无法一一对应的锚点区间。

验收：任意chunk必须映射回指定`source_version + source_hash`的精确原文字节范围；仅“文本看起来相似”不合格。

## 3. chunk_profile与稳定ID

`chunk_profile`至少固定：

- `chunk_profile_version`；
- 文档结构识别版本；
- 章节、场景、段落、句子边界规则；
- 父块和子块的目标长度与最大长度；
- 长度计量使用的tokenizer或字节规则及版本；
- 超长块降级规则；
- 重叠规则；
- 空块与跨章节块规则。

切分优先级：

```text
章节/场景边界
→ 段落边界
→ 句子边界
→ 仅在超长时使用已版本化降级规则
```

不得把固定token滑窗作为唯一语义边界。检索子块可以较小，父块提供场景或章节上下文。

`chunk_id`由以下字段的规范序列化结果计算SHA-256：

```text
chunk_id_algorithm_version
project_id + scope
source_artifact_id + source_version + source_hash
chunk_profile_version
normalized_start + normalized_end
chunk_content_hash
```

约束：

- 禁止随机UUID、自增ID和当前时间。
- 相同来源、配置和边界重建后，chunk_id完全相同。
- 来源版本、内容、边界或切分配置变化时，不得复用旧chunk_id。
- chunk记录另存`parent_chunk_id`、规范化区间、原文区间和content hash。

## 4. embedding_profile与index_profile

`embedding_profile`必须包含：

```text
provider
model
model_revision
dimension
vector_dtype
normalization
distance
document_input_template
query_input_template
embedding_profile_version
```

`index_profile`必须包含：

```text
index_algorithm
index_algorithm_version
construction_parameters
search_parameters
quantization_profile
index_profile_version
```

物理索引按兼容键隔离：

```text
vector_contract_version
+ normalizer配置
+ chunk_profile
+ embedding_profile
+ distance
+ dimension
+ index_profile
```

- 维度相同不代表兼容。
- `vector_profile_guard`必须在外部向量提交、索引创建、重建、查询编译、候选检索和代际切换时执行。
- 外部向量必须校验来源chunk hash、维度、有限数值与范数。
- MCP核心不加载embedding模型。

## 5. 查询端

查询必须携带或解析出：

- 目标索引兼容的normalizer配置；
- 目标索引兼容的embedding配置；
- 外部计算的查询向量，或查询向量模块的明确引用；
- `project_id`和显式`scope`；
- `candidate_k`、`top_k`和该profile的阈值；
- 当前版本或历史版本查询意图。

允许作用域：

| scope | 语义 |
|---|---|
| `project` | 默认，仅当前项目 |
| `global` | 仅人工晋升的总记忆 |
| `project_plus_global` | 当前项目＋总记忆，结果分别标记来源 |

不提供任意枚举多个其他项目ID的查询能力。

**对齐不等于机械使用同一切分器：**

- 文档需要语义父子chunk，形成可检索单元。
- 短查询作为完整文本直接归一化和嵌入，不经过文档chapter/scene/paragraph chunker，不生成文档offset_map。
- 文档和查询分别使用`document_input_template`与`query_input_template`；两者是否相同由embedding模型契约决定。

## 6. 检索顺序

```text
兼容配置检查
→ 项目/总记忆作用域过滤
→ 默认过滤非当前权威版本
→ 取candidate_k候选
→ 距离或分数阈值过滤
→ 按distance、chunk_id确定性排序
→ 去重
→ 截取top_k
→ 有界父子上下文扩展
→ 按chunk绑定的source version/hash物化精确原文
```

约束：

- `candidate_k >= top_k`。
- 阈值按profile标定，不设跨模型通用阈值。
- 去重至少覆盖相同chunk_id，以及相同`source_hash + 原文区间`。
- 父子扩展必须限制父块数、字符数与总预算，且不能跨越作用域或权限。
- 默认查询不返回被新版本取代的chunk；历史查询必须标`historical=true`。
- 物化不得偷换成最新稿。

每个`ContextItem`至少返回：

```text
chunk_id
distance_or_score
project_id + scope
source_artifact_id + source_version + source_hash
原文区间与精确摘录
parent_context
chunk_profile_version + embedding_profile_version
```

人工选取的上下文也使用同一`ContextItem`，以后接入向量后端不得改变角色工具schema。

## 7. 索引重建与删除

重建：

1. 新配置或新来源创建新索引代际；
2. 构建期间旧代际继续只读服务；
3. 校验chunk数、hash、维度、作用域及抽样原文映射；
4. 原子切换代际指针；
5. 旧代际按保留策略清理并记录事件。

删除：

- 支持按项目、source artifact、source version、chunk_id删除；
- 同时删除向量、chunk元数据、父子关系与查询缓存；
- 操作幂等并留tombstone，防止旧重建任务复活数据；
- 删除项目不影响总记忆中已独立晋升的副本，但其原始血缘保留；
- 所有重建、切换和删除写审计事件。

## 8. 固定验收门禁

| 验收项 | 最低标准 |
|---|---|
| 固定问题集Recall@10 | ≥0.90 |
| 精确来源版本与原文区间 | 100%正确 |
| 错误项目污染 | 0条 |
| 未授权总记忆污染 | 0条 |
| 默认查询返回过期版本 | 0条 |
| 不兼容配置 | 检索前100%拒绝 |
| 同配置重建chunk_id稳定性 | 100% |
| 切分边界golden cases | 100%符合预期 |
| 相同查询重复排序 | 同一索引代际下确定一致 |
| 删除后重建或旧任务回流 | 已删记录不得复活 |

golden集必须覆盖短查询、跨段语义、父子扩展、同名跨项目、旧版本、不同embedding revision和不同chunk profile。每个报告必须记录golden集版本、索引代际和全部profile。

## 9. MVP边界

- V01实现全部schema、错误、兼容矩阵、固定夹具和符合性测试。
- V01允许没有生产向量后端；调用检索必须明确返回`VECTOR_BACKEND_UNAVAILABLE`，不得静默改用无关检索。
- V02实现预切分端，V03实现检索端，V04实现治理与质量门禁。
- 后续真正导入向量模型时，由用户与另一AI共同优化和评估；不得绕开本契约改角色接口。
