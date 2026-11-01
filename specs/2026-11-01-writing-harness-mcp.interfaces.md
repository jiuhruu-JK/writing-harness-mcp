# 写作 Harness MCP · 接口总表（规范附件）

本文件是全部叶子模块 `run(payload: dict) -> dict` 业务字段的单一事实源。公共 envelope、actor、project作用域和稳定错误码见主 spec 的「接口」节。

## 通用约定

- 所有写模块必须要求 `idempotency_key`；同 actor、同 key、同请求返回首次结果，同 key 不同请求返回 `IDEMPOTENCY_KEY_REUSE`。
- 所有提交类模块必须带 `base_revision` 或 `base_version_id`；过期即返回 `STALE_BASE` 或 `LEASE_EXPIRED`。
- 所有读取类模块必须带项目作用域；跨项目一律 `PROJECT_SCOPE_VIOLATION`。
- `role` 由模块身份固定，客户端不得通过 payload 冒充其他角色。
- 表格中的“专属错误”是模块异常的本模块条件；此外仍需支持主 spec 列出的通用错误码。

## 一、项目、版本与审计

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `project_registry` | `action, root_path, name` | `project_id, schema_version, data_root` | 数据根重复、非法路径 |
| `sqlite_migration` | `database_path, migrations_root` | `applied_versions, current_version` | 迁移顺序冲突、迁移失败 |
| `artifact_commit` | `chapter_id, artifact_kind, logical_path, content, base_version_id, run_id` | `version_id, sha256, commit_id` | 空内容、base过期、镜像冲突 |
| `artifact_resolve` | `version_id, expected_hash, include_content` | `content_or_ref, metadata, source_ref` | 版本不存在、哈希不符 |
| `artifact_diff` | `left_version_id, right_version_id` | `hunks, stats, left_sha256, right_sha256` | 版本不存在、跨项目比较 |
| `lineage_trace` | `target_version_id, direction, depth` | `nodes, edges, context_manifest` | 目标不存在、超深度 |
| `rollback_commit` | `target_version_id, base_version_id, reason, decision_id` | `new_version_id, sha256, invalidated_decisions` | 目标不在同一artifact、无人工裁决 |
| `event_append` | `event_type, entity_ref, payload_path, correlation_id, causation_id` | `event_seq, event_id, payload_sha256` | 实体不存在、payload哈希不符 |
| `event_read` | `filters, cursor, limit` | `events, next_cursor` | 非法游标、超限 |
| `human_lock` | `action(set/release/status), scope_type, scope_id, reason` | `lock_id, active, owner_id` | 非人角色设置/释放、锁已存在 |

## 二、工作流内核

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `workflow_transition` | `chapter_id, from_state, to_state, base_revision, decision_id` | `state, revision, allowed_next` | 非法迁移、版本过期、缺人工批准 |
| `workflow_parallel_join` | `chapter_id, batch_id, expected_branch_ids, closed` | `joined, missing_branch_ids, base_version_id` | 批次未关闭、分支base不一致 |
| `stage_outline_big_payoff` | `chapter_id, run_id, outline_ref, big_payoff_ref, decision_id` | `passed, blockers` | 人大纲/大爽点未批准 |
| `stage_ai_draft` | `chapter_id, run_id, draft_ref, outline_ref, base_revision` | `passed, blockers` | 输入越界、草稿缺失 |
| `stage_serial_logic_review` | `chapter_id, run_id, slice_index, reviewed_ref, facts_ref, base_revision` | `passed, blockers, next_slice` | 非串行、前片未落盘 |
| `stage_style_candidates` | `chapter_id, batch_id, candidate_refs, base_version_id, expected_count` | `passed, blockers` | 候选未关闭、base不一致 |
| `stage_logic_correction` | `chapter_id, batch_id, corrected_ref, facts_ref, base_version_id` | `passed, blockers` | 候选批次未关闭、遗漏候选血缘 |
| `stage_small_payoff` | `chapter_id, run_id, output_ref, decision_id, base_revision` | `passed, blockers` | 与疲劳阶段混合、未经人工复核 |
| `stage_fatigue_review` | `chapter_id, run_id, output_ref, evidence_ref, decision_id` | `passed, blockers` | 非独立审核、未经人工复核 |
| `stage_human_voice` | `chapter_id, run_id, voice_ref, transcript_ref, decision_id` | `passed, blockers` | 非人类提交、原始转写缺失 |
| `stage_conservative_cleanup` | `chapter_id, run_id, cleaned_ref, transcript_ref, base_revision` | `passed, blockers, flagged_ref` | 修改事实、未生成标记清单 |
| `stage_human_polish` | `chapter_id, run_id, polished_ref, decision_id, journal_id` | `passed, blockers` | 无操作日志、非人类提交 |
| `stage_tts` | `chapter_id, run_id, tts_artifact_ref, source_version_id` | `passed, blockers` | 源版本不符、媒体未登记 |
| `stage_human_listening` | `chapter_id, run_id, fixed_audio_ref, decision_id` | `passed, blockers` | 非人类提交、音频未绑定版本 |
| `stage_delivery` | `chapter_id, run_id, delivery_manifest, source_version_id, decision_id` | `passed, blockers, delivered_version_id` | 缺最终批准、清单与版本不符 |
| `stage_reflow` | `chapter_id, delivered_version_id, accepted_refs` | `candidate_ids, passed` | 非定稿、跨项目引用 |

## 三、人类与外部工具提交

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `outline_approval_tool` | `chapter_id, outline_version_id, big_payoff_version_id, decision` | `decision_id, approved_version_hash` | 非人类、目标版本变化 |
| `voice_reconstruction_tool` | `chapter_id, transcript_text, audio_ref, raw_metadata, base_version_id` | `version_id, transcript_version_id` | 无原始留底、修改他人版本 |
| `human_polish_tool` | `chapter_id, base_version_id, final_text, intent, searched_refs, accepted_refs, rejected_refs` | `version_id, journal_id, diff_ref` | 非人类、日志关联失败 |
| `listening_fix_tool` | `chapter_id, base_audio_version_id, fixed_audio_ref, notes` | `media_version_id` | 非人类、音频源不符 |
| `delivery_finalize_tool` | `chapter_id, delivery_version_id, decision, manifest_ref` | `decision_id, delivered_version_id` | 非人类、版本或哈希不符 |
| `tts_artifact_tool` | `chapter_id, source_version_id, media_ref, generator_metadata` | `media_artifact_id, media_version_id` | 源版本不存在、媒体哈希不符 |

## 四、七角色接口

### 通用角色形状

| 模块后缀 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `_assignment_tool` | `run_id` | `assignment_id, stage, task, output_schema_uri, prompt_uri, prompt_version, budget` | 错误角色、无可用任务 |
| `_submission_tool` | `assignment_id, base_version_id, context_manifest_id, output, idempotency_key` | `version_id, sha256, lineage_id` | 角色不匹配、上下文越权、过期base、人锁 |
| `_context` | `assignment_id, budget` | `context_items, used_budget, remaining_budget` | 越权上下文、超预算 |
| `_prompt` | `prompt_version` | `template, output_schema_uri, version` | 版本不存在、角色不匹配 |

角色专属限制：

| 角色 | `_context` 可见白名单 | 明确不可见 |
|---|---|---|
| `draft` | 人大纲、大爽点、上一章定稿、已批准项目记忆 | 其他角色prompt、review结果 |
| `logic_review` | 本片、最新事实账本、大纲白名单、相关正典 | 文风候选、后续阶段产物 |
| `style_imitation` | 固定输入版本、指定外部修辞范本 | 其他项目记忆、内部生成范本 |
| `logic_correction` | 固定原稿、已关闭候选批次、当前正典、事实账本 | 未关闭候选、其他角色prompt |
| `small_payoff` | 汇合稿、大爽点、已确认小爽点规则 | 疲劳审核prompt与历史 |
| `fatigue_review` | 小爽点完成稿、历史检索证据、频次账本 | 小爽点生成prompt |
| `conservative_cleanup` | 人语音重构稿及原始转写、保守整理约束 | 文风候选、小爽点prompt |

每个角色的四个模块名称分别为 `<role>_assignment_tool`、`<role>_submission_tool`、`<role>_context`、`<role>_prompt`，共28个叶子模块。

## 五、记忆与外部修辞

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `memory_candidate` | `source_version_id, kind, content, evidence_refs` | `candidate_id, status` | 来源非已接受产物、跨项目引用 |
| `memory_curation` | `candidate_ids, decisions, merged_text, target_scope` | `memory_ids, superseded_ids` | 无人工确认、非法合并 |
| `memory_scope_guard` | `requested_scope, project_id, query` | `allowed_scope, filters` | 任意枚举其他项目、总记忆未授权 |
| `memory_promotion` | `memory_ids, decision_id, global_content, redaction_report` | `global_memory_ids, lineage` | 无人工批准、未脱敏 |
| `rhetoric_external_import` | `work_metadata, source_license, excerpts, artifact_refs` | `external_artifact_id, imported_count` | 作者定稿、缺来源/许可 |

## 六、向量预切分端

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `vector_source_bind` | `source_artifact_id, source_version, source_hash, kind, scope` | `source_ref_id, verified` | 哈希/版本不符、禁入来源 |
| `vector_normalize` | `source_ref_id, normalizer_profile` | `normalized_ref, normalizer_version, offset_map_ref` | 配置不支持、映射不完整 |
| `vector_chunk` | `normalized_ref, chunk_profile` | `chunk_ids, parent_relations, profile_version` | 非法边界规则、空块 |
| `vector_chunk_id` | `source_ref, chunk_profile, normalized_span, content_hash` | `chunk_id` | 字段缺失、算法版本未知 |
| `vector_profile_guard` | `normalizer_profile, chunk_profile, embedding_profile, index_profile, operation` | `compatible, compatibility_key` | 配置混用、维度相同但revision/distance不同 |

## 七、向量检索端

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `vector_embedding_accept` | `chunk_id, vector, embedding_profile, chunk_hash` | `vector_id, stored` | 维度不符、非有限值、范数不符、chunk_hash不符 |
| `vector_query_compile` | `query_text_or_vector, scope, embedding_profile, target_index_profile, historical, candidate_k, top_k` | `query_spec_id, filters, thresholds` | profile不兼容、作用域非法、candidate_k<top_k |
| `vector_candidate_search` | `query_spec_id, index_generation` | `candidates, generation` | 索引代际不可用、作用域越权 |
| `vector_rank` | `candidates, threshold, top_k` | `ranked_items` | 阈值非法、重复记录无法归并 |
| `vector_context_expand` | `ranked_items, max_parents, max_chars, max_budget` | `expanded_items, used_budget` | 跨作用域扩展、超预算 |
| `vector_materialize` | `chunk_ids, source_version_policy` | `context_items` | 原文版本缺失、offset不符、默认历史违规 |

## 八、向量治理

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `vector_index_rebuild` | `source_bindings, profiles, generation_label` | `generation_id, validated, activated` | 校验失败、旧代际不可读 |
| `vector_index_delete` | `scope, selectors, reason, decision_id` | `tombstone_ids, deleted_count` | 非人工授权总记忆删除、选择器为空 |
| `vector_quality_eval` | `golden_set_version, index_generation` | `recall_at_10, source_accuracy, pollution_counts, profile_rejections` | golden集缺失、指标不达标 |

## 九、MCP组合与传输

| 模块 | 业务入参 | 返回 data | 专属错误条件 |
|---|---|---|---|
| `mcp_server` | `action(compose/describe), config` | `app_descriptor, role_tool_matrix, schema_versions` | 模块注册冲突、角色泄漏 |
| `mcp_stdio_transport` | `action(start/stop/status), server_config` | `transport_status, process_id` | 重复启动、服务未就绪 |
| `mcp_http_transport` | `action(start/stop/status), bind_host, port, server_config` | `transport_status, base_url` | 非loopback默认暴露、绑定失败 |

## 叶子模块总清单

项目与版本：`project_registry`、`sqlite_migration`、`artifact_commit`、`artifact_resolve`、`artifact_diff`、`lineage_trace`、`rollback_commit`、`event_append`、`event_read`、`human_lock`。

工作流：`workflow_transition`、`workflow_parallel_join`、`stage_outline_big_payoff`、`stage_ai_draft`、`stage_serial_logic_review`、`stage_style_candidates`、`stage_logic_correction`、`stage_small_payoff`、`stage_fatigue_review`、`stage_human_voice`、`stage_conservative_cleanup`、`stage_human_polish`、`stage_tts`、`stage_human_listening`、`stage_delivery`、`stage_reflow`。

人类与外部提交：`outline_approval_tool`、`voice_reconstruction_tool`、`human_polish_tool`、`listening_fix_tool`、`delivery_finalize_tool`、`tts_artifact_tool`。

七角色：`draft`、`logic_review`、`style_imitation`、`logic_correction`、`small_payoff`、`fatigue_review`、`conservative_cleanup` 各包含 `_assignment_tool`、`_submission_tool`、`_context`、`_prompt`。

记忆：`memory_candidate`、`memory_curation`、`memory_scope_guard`、`memory_promotion`、`rhetoric_external_import`。

向量预切分：`vector_source_bind`、`vector_normalize`、`vector_chunk`、`vector_chunk_id`、`vector_profile_guard`。

向量检索：`vector_embedding_accept`、`vector_query_compile`、`vector_candidate_search`、`vector_rank`、`vector_context_expand`、`vector_materialize`。

向量治理：`vector_index_rebuild`、`vector_index_delete`、`vector_quality_eval`。

MCP：`mcp_server`、`mcp_stdio_transport`、`mcp_http_transport`。

总计82个叶子模块。任务卡必须与清单逐字一致。
