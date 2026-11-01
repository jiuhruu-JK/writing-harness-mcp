# 写作 Harness MCP · 对话与模块批次

## 原话落档

### 2026-11-01 工作流与模块边界

> 这个工作流啊基本上没啥问题了。但是还存在一定的问题，就是说这个爽点机制，你得帮我修正一下这个工作流。还有一个就是爽点。对于爽点的定义存在诸多的问题。

> 这个本质上是在造一个Harness一个写作Harness所以它应该具有自进化的功能然后爽点机制就是自进化的功能应该是。

> 还得增加一个东西，就是说在机制当中增加一个东西。在爽点机制后面，审核一个审核AI这里要增加一个逻辑审核AI，要增加一个额外逻辑审核AI，那就是什么？那就是审美疲劳审核AI。它写出来的这个爽点呀，它要保证不能让读者审美疲劳，不能重复，太过于重复。这是另一个，就是说和这个语音整理啊、重构啊，这些是同级别的模块。它并不能合并，你并不能合并到这个爽点里面。

> 因为爽点只负责归类，只负责禁止AI写什么东西，然后提建议AI写什么东西。

> 这个爽点，它应该是什么？它存在两种模式，它应该是存在两种模式的开关。应该一种是什么？就是我足够积累的这个爽点库足够多了，然后禁止库也足够多了，然后让AI自动化就可以了。但是前期这个库资料不够多，所以我还得和AI交谈，就是说交谈模式来再累积爽点，来增加这个素材。

> 这个树状图应该以这个工作流为基础，以时间线为基础。这个库，这些什么工具啊，都是呃都是这个树状对应的工作流程使用的工具。

> 人类它应该有一个裁决记录，就是说走留下日志……这些日志也是作为记忆库的一部分。然后让什么让仿写AI，让这个审核AI进行吸收，让爽点AI进行吸收。

> 修辞库我会定期的更新某本书，不会把这个稿件，我自己写的稿件塞进去，这个修辞库是别人写好的稿子，然后我复用他的修辞。

> 这个记忆机制还得分为两种记忆机制。一种是什么？只服务我当前这本书的……另一种……服务于所有书的，就是说所有书都可以复用。

> 要提醒这个人类工作的时候要定期整理这些记忆。怎么整理呢？派这个整理AI去进行整理。

### 2026-11-01 MCP、模块最小化与向量

> 我们要把这个东西做成一个MCP……他们的工作区域就是当前文件夹，就可以复用同用复用一个同一个MCP，同一个文件夹，然后同一套记忆，所有的AI都可以复用这些东西。

> 项目要开源……面向有经验写作者……适配主流Agent/MCP客户端，要求主流传输方式都支持。

> 打回去，没有做到这个最小化的模块拆分。我都说了，最小化是什么？就是拆的时候不能再拆了，才能算是最小化。

> 这个Review的工具，你为什么会把这些工具全部塞在一起？逻辑审核，他们的提示词都是不是同一套。你让这个AI他们使用同一套提示词吗？这不会，这不是增加上下文的成本吗？

> 向量库想要搜索的精准，首先要保证这个，就是说切分端就是预切分端，还有这个检索端，都好，都得做好对齐。

> 我会导入一个向量模型，进行这个具体的优化和评估。到时候我会配合另一个AI进行评估。

> 你只负责写Spec和工作包，写了写完这些工作包，然后就交接给另一个AI了。

> 不要预留商业化边界，我们这个模块化的工作足够支撑我后续开发增加功能了。

## 模块批次

【模块批次 1】
- project_registry —— 判定：自造 —— 理由：项目身份和数据根隔离属于本产品核心边界
- sqlite_migration —— 判定：自造 —— 理由：迁移顺序和模块归属规则需要独立验收
- artifact_commit —— 判定：自造 —— 理由：不可变快照和原子提交是本产品版本权威
- artifact_resolve —— 判定：自造 —— 理由：精确历史读取必须与控制提交分开验收

【模块批次 2】
- artifact_diff —— 判定：自造 —— 理由：版本差异需要独立的确定性和可复现验收
- lineage_trace —— 判定：自造 —— 理由：输入输出与上下文血缘必须独立追溯
- rollback_commit —— 判定：自造 —— 理由：回滚创建新版本与普通提交职责不同
- event_append —— 判定：自造 —— 理由：审计事件追加需要独立顺序和哈希约束

【模块批次 3】
- event_read —— 判定：自造 —— 理由：审计查询与事件写入具有不同权限和分页语义
- human_lock —— 判定：自造 —— 理由：人类锁必须独立于租约并跨重启保持
- workflow_transition —— 判定：自造 —— 理由：主线迁移合法性不能散落在各阶段模块
- workflow_parallel_join —— 判定：自造 —— 理由：并行汇合条件需要单独验收

【模块批次 4】
- stage_outline_big_payoff —— 判定：自造 —— 理由：人类大爽点门禁是独立阶段
- stage_ai_draft —— 判定：自造 —— 理由：草稿阶段输入边界需要独立门禁
- stage_serial_logic_review —— 判定：自造 —— 理由：按片串行审核必须独立控制落盘顺序
- stage_style_candidates —— 判定：自造 —— 理由：并行候选批次只允许侧支写入

【模块批次 5】
- stage_logic_correction —— 判定：自造 —— 理由：候选关闭后的串行校正与候选生成职责不同
- stage_small_payoff —— 判定：自造 —— 理由：小爽点阶段由独立角色和工具服务
- stage_fatigue_review —— 判定：自造 —— 理由：审美疲劳模块与爽点模块明确不可合并
- stage_human_voice —— 判定：自造 —— 理由：人类语音重构阶段必须禁止AI代提交

【模块批次 6】
- stage_conservative_cleanup —— 判定：自造 —— 理由：语音整理只能保守处理并保留标记
- stage_human_polish —— 判定：自造 —— 理由：精修阶段需要绑定无感日志和人工裁决
- stage_tts —— 判定：自造 —— 理由：外部媒体产物登记需要精确源版本
- stage_human_listening —— 判定：自造 —— 理由：听感修复属于人类独立阶段

【模块批次 7】
- stage_delivery —— 判定：自造 —— 理由：交付版本固定和最终批准需要独立门禁
- stage_reflow —— 判定：自造 —— 理由：回流只生成项目候选且不得改写定稿
- outline_approval_tool —— 判定：自造 —— 理由：大爽点批准工具必须和阶段门禁分离
- voice_reconstruction_tool —— 判定：自造 —— 理由：人类语音提交需要原始转写留底

【模块批次 8】
- human_polish_tool —— 判定：自造 —— 理由：精修提交必须自动关联意图、检索和采选日志
- listening_fix_tool —— 判定：自造 —— 理由：人类听感修复提交是独立工具
- delivery_finalize_tool —— 判定：自造 —— 理由：最终审美批准只能由人绑定精确版本
- tts_artifact_tool —— 判定：自造 —— 理由：外部TTS产物提交是独立外部边界

【模块批次 9】
- draft_assignment_tool —— 判定：自造 —— 理由：草稿角色取任务schema必须独立
- draft_submission_tool —— 判定：自造 —— 理由：草稿角色交结果schema必须独立
- draft_context —— 判定：自造 —— 理由：草稿上下文白名单和预算必须独立
- draft_prompt —— 判定：自造 —— 理由：草稿提示词不得与其他角色共用

【模块批次 10】
- logic_review_assignment_tool —— 判定：自造 —— 理由：逻辑审核取任务schema必须独立
- logic_review_submission_tool —— 判定：自造 —— 理由：逻辑审核交结果schema必须独立
- logic_review_context —— 判定：自造 —— 理由：逻辑审核只应看到本片和最新事实
- logic_review_prompt —— 判定：自造 —— 理由：逻辑审核提示词不得与其他review共用

【模块批次 11】
- style_imitation_assignment_tool —— 判定：自造 —— 理由：文风仿写取任务schema必须独立
- style_imitation_submission_tool —— 判定：自造 —— 理由：文风候选产物schema必须独立
- style_imitation_context —— 判定：自造 —— 理由：仿写上下文只读固定输入和外部范本
- style_imitation_prompt —— 判定：自造 —— 理由：仿写提示词必须与逻辑校正分开

【模块批次 12】
- logic_correction_assignment_tool —— 判定：自造 —— 理由：逻辑校正取任务schema必须独立
- logic_correction_submission_tool —— 判定：自造 —— 理由：校正产物schema与候选产物不同
- logic_correction_context —— 判定：自造 —— 理由：校正必须读取已关闭候选批次和当前正典
- logic_correction_prompt —— 判定：自造 —— 理由：逻辑校正提示词不能复用逻辑审核提示词

【模块批次 13】
- small_payoff_assignment_tool —— 判定：自造 —— 理由：小爽点取任务schema必须独立
- small_payoff_submission_tool —— 判定：自造 —— 理由：小爽点产物schema必须独立
- small_payoff_context —— 判定：自造 —— 理由：小爽点只读本角色规则和大爽点约束
- small_payoff_prompt —— 判定：自造 —— 理由：小爽点提示词不得暴露给疲劳角色

【模块批次 14】
- fatigue_review_assignment_tool —— 判定：自造 —— 理由：疲劳审核取任务schema必须独立
- fatigue_review_submission_tool —— 判定：自造 —— 理由：疲劳审核产物schema必须独立
- fatigue_review_context —— 判定：自造 —— 理由：疲劳上下文只读检索证据和频次账本
- fatigue_review_prompt —— 判定：自造 —— 理由：疲劳提示词不得暴露给小爽点角色

【模块批次 15】
- conservative_cleanup_assignment_tool —— 判定：自造 —— 理由：保守整理取任务schema必须独立
- conservative_cleanup_submission_tool —— 判定：自造 —— 理由：保守整理产物和标记schema必须独立
- conservative_cleanup_context —— 判定：自造 —— 理由：整理上下文只读语音稿和保守约束
- conservative_cleanup_prompt —— 判定：自造 —— 理由：整理提示词不得与其他角色共用

【模块批次 16】
- memory_candidate —— 判定：自造 —— 理由：记忆候选只能来自已接受产物
- memory_curation —— 判定：自造 —— 理由：去重、质量和冲突整理需要人工复核
- memory_scope_guard —— 判定：自造 —— 理由：项目与总记忆作用域必须强制隔离
- memory_promotion —— 判定：自造 —— 理由：跨项目晋升必须绑定人工决策和血缘

【模块批次 17】
- rhetoric_external_import —— 判定：自造 —— 理由：外部修辞来源和作者定稿禁入必须独立裁决
- vector_source_bind —— 判定：自造 —— 理由：向量来源必须精确绑定artifact版本与哈希
- vector_normalize —— 判定：自造 —— 理由：归一化和原文offset映射必须独立验收
- vector_chunk —— 判定：自造 —— 理由：语义切分与chunk配置必须独立于检索

【模块批次 18】
- vector_chunk_id —— 判定：自造 —— 理由：稳定chunk_id需要独立算法版本和golden向量
- vector_profile_guard —— 判定：自造 —— 理由：配置兼容性必须在所有入口独立裁决
- vector_embedding_accept —— 判定：自造 —— 理由：外部向量来源与数值校验必须独立
- vector_query_compile —— 判定：自造 —— 理由：查询归一化、模板和作用域必须独立编译

【模块批次 19】
- vector_candidate_search —— 判定：自造 —— 理由：候选召回只负责兼容索引中的候选获取
- vector_rank —— 判定：自造 —— 理由：阈值、排序和去重必须与召回分离
- vector_context_expand —— 判定：自造 —— 理由：父子上下文扩展需要独立预算边界
- vector_materialize —— 判定：自造 —— 理由：精确原文物化必须独占原文版本约束

【模块批次 20】
- vector_index_rebuild —— 判定：自造 —— 理由：索引代际构建和原子切换必须独立验收
- vector_index_delete —— 判定：自造 —— 理由：删除与墓碑防止复活需要独立治理
- vector_quality_eval —— 判定：自造 —— 理由：固定golden集质量门禁必须独立运行
- mcp_server —— 判定：自造 —— 理由：角色会话路由和组合根不承载业务schema

【模块批次 21】
- mcp_stdio_transport —— 判定：自造 —— 理由：stdio生命周期必须与HTTP分开验收
- mcp_http_transport —— 判定：自造 —— 理由：Streamable HTTP生命周期必须独立监听与关闭
