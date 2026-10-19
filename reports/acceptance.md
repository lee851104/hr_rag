# MVP 驗收對照（7.5）

2026-10-19。逐項對照五份規格的全部 Requirement 與 Scenario，並列出證據。

**結論：MVP 未標記完成。** 唯一未通過的硬門檻是授權執行 **11/12**：保留題 H09 的 employee 角色預期回「資料不足」，實際回了答案。答案只引用三角色可讀的 C01，沒有限閱內容外洩，使用者也判定答案正確；但依事先凍結的規則，狀態不符即計為失敗。使用者決定照實記錄、不事後改判、不為此修改系統（[stage-7-holdout.md](stage-7-holdout.md)）。依 *Release veto*，任何授權測試失敗都不能標記第一版完成。其餘門檻與 Scenario 均有證據通過。

證據縮寫：測試 `tests/<檔>::<函式>`；報告 `reports/<檔>`。完整測試：開發環境 494 passed／1 skip（`stage7-freeze-tests.xml`）；乾淨環境重建結果見 7.4（下方）。

## knowledge-corpus

| Requirement／Scenario | 證據 | 結果 |
|---|---|---|
| Assigned document maintenance／Review becomes due | test_manifest::test_valid_and_due、test_unknown_section_date_and_missing_publisher；manifest 維護者與 2026-11-17 到期 | 通過 |
| Incremental embedding reuse／Change one existing document | test_ingestion::test_change_one_document_only_recomputes_its_changed_text；stage-2.md 呼叫數 | 通過 |
| ／Metadata only update | test_ingestion::test_metadata_only_update_reuses_vectors_and_updates_visibility、test_citation_access::test_metadata_publication_changes_existing_session_and_citations | 通過 |
| Fixed and attributable corpus／Count and provenance | test_manifest::test_default_fixed_counts、test_fixed_version_distribution；test_stage1_data；README 撰寫者揭露 | 通過 |
| Separate dates and effective intervals／Transition boundary | test_versions::test_version_transition_and_section_dates；test_policy::test_half_open_dates_and_missing_acl_deny | 通過 |
| ／Unknown effective date | test_chunking::test_unknown_section_date_fails_closed；test_versions::test_invalid_manifest_is_quarantined_without_partial_publish | 通過 |
| ／ROC calendar dates | test_manifest::test_roc | 通過 |
| ／Interpretive Q&A without effective date | test_source_text::test_qa_publication_is_not_footer_update | 通過 |
| Preserve evidence structure／Trace a chunk | test_chunking::test_actual_tokenizer_bounds_and_exact_source_spans；stage-2.md 20片段人工核對 | 通過 |
| ／Article longer than the encoder limit | test_chunking::test_oversize_sentence_is_rejected_without_truncation | 通過 |
| Repeatable and recoverable ingestion／Failed update | test_ingestion::test_failed_generation_preserves_active、test_snapshot_write_failure_preserves_active | 通過 |
| ／Withdrawn source | test_versions::test_withdrawal_filters_vectors_parents_and_survives_reingest；test_web::test_withdrawn_source_hides_dependent_answer | 通過 |

## access-control

| Requirement／Scenario | 證據 | 結果 |
|---|---|---|
| Protect replay and feedback records／Revoke after an answer | test_web::test_role_downgrade_hides_previous_restricted_claims、test_withdrawn_source_hides_dependent_answer、test_feedback_is_owner_only_enum_and_shows_status_only、test_no_global_replay_or_trace_endpoint | 通過 |
| Server authenticated identity／Spoof a role | test_auth::test_frontend_role_never_escalates；test_web::test_query_accepts_only_question_and_as_of、test_query_uses_session_role_and_renders_answer_with_citations | 通過 |
| Enforce the document matrix before retrieval／Role matrix | test_policy::test_role_matrix；test_retrieval::test_prefilter_excludes_high_similarity_forbidden_and_expired、test_missing_acl_denied_before_any_scoring；瀏覽器三角色（stage-6.md） | 通過 |
| ／Outbound generation request | test_prompt_injection::test_injected_question_document_and_citation_never_elevate（摘要與原文兩種生成器） | 通過 |
| Protect secondary access paths／Guess a citation identifier | test_citation_access::test_missing_forbidden_and_withdrawn_identical；test_web::test_records_are_owner_only_and_indistinguishable | 通過 |
| Prevent cross request leakage／HR then employee | test_citation_access::test_parallel_http_sessions_keep_separate_context；test_policy::test_parallel_accounts_and_sequential_downgrade；test_web::test_logout_form_clears_screen_and_session | 通過 |

## evidence-retrieval

| Requirement／Scenario | 證據 | 結果 |
|---|---|---|
| Versioned Chinese query normalization／Equivalent and distinct leave terms | test_query::test_synonyms_preserve_distinct_leave_negation_numbers_and_dates；test_retrieval::test_synonym_pair_hits_same_required_group | 通過 |
| ／Query too long for the encoder | test_query::test_query_limit_checks_both_tokenizers_without_truncation；test_retrieval::test_long_query_never_calls_encoder | 通過 |
| Bounded and traceable context assembly／Repeated parent and conflicting sources | test_context::test_same_parent_dedup_relevance_and_citation_whitelist、test_identical_text_different_source_scope_never_overwrites | 通過 |
| ／Budget cannot retain a complete rule | test_context::test_parent_withdrawal_rechecks_and_budget_removes_whole_units、test_prompt_itself_over_budget_is_controlled | 通過 |
| ／Relevance filter removes noise | test_context::test_filter_keeps_first_but_never_unauthorized | 通過 |
| ／Explicit different leave category | test_context::test_explicit_different_leave_grant_is_noise、test_ambiguous_general_or_related_scope_is_preserved | 通過 |
| Date scoped retrieval／Missing historical evidence | test_versions；test_retrieval::test_prefilter_excludes_high_similarity_forbidden_and_expired | 通過 |
| ／Explicit ROC date in the question | test_policy::test_explicit_conflict_displays_both_dates、test_relative_or_matching_period_has_no_conflict；test_retrieval::test_date_conflict_does_not_call_models | 通過 |
| Comparable retrieval modes／Controlled comparison | test_evaluation::test_comparison_rejects_different_snapshot；stage-4.md；stage-7-official.md（三模式即時重現） | 通過 |
| Preserve complete supporting evidence／Cross document question | test_context::test_context_uses_actual_provider_budget；test_verbatim::test_verbatim_expands_explicit_document_and_rule_references | 通過 |
| Retrieval acceptance gate／Averages cannot hide leakage | 開發 rerank Top-5 14/14、組裝後 14/14、精確度 82.14%、授權錯誤 0；全30題 Top-5／組裝後 21/22（保留 7/8） | 通過 |
| Compound clause reranking／Secondary clause evidence | test_retrieval::test_compound_rerank_retains_independent_second_clause 等3項 | 通過 |

## grounded-answering

| Requirement／Scenario | 證據 | 結果 |
|---|---|---|
| Stable evidence based responses／Three independent requests | 6案例×3次 18/18（使用者核對，stage-5-acceptance.md） | 通過 |
| Grounded and labeled claims／Official plus company process | test_answering::test_source_labels_and_citation_metadata；瀏覽器 manager D15（C03＋C01 分別標示） | 通過 |
| ／Simplified Chinese output | test_answering::test_simplified_output_rejected、test_simplified_reason_rejected | 通過 |
| ／Compact citation transport | test_openai_provider::test_long_citation_ids_use_verified_short_transport_ids；test_verbatim::test_verbatim_wire_constrains_ids_not_document_names | 通過 |
| Unsupported and conflicting answers／Personal remaining leave | test_answering::test_personal_balance_cannot_be_invented_from_general_rules | 通過 |
| ／Conflicting company rule | test_answering::test_conflicting_official_and_company_fixture_reaches_generator、test_partial_and_conflict_status_preserved | 通過 |
| Treat retrieved instructions as data／Document injection and invented citation | test_prompt_injection；test_answering::test_unknown_citation_rejected | 通過 |
| Controlled external generation／Missing API key | test_openai_provider::test_unconfigured_does_not_send | 通過 |
| ／Load local generation settings | test_environment（8項） | 通過 |
| ／Cost limit reached | test_openai_provider::test_cost_limit_zero_and_insufficient_reservation；test_web::test_generation_unavailable_is_understandable | 通過 |
| ／Rate limit or server error | test_openai_provider::test_bounded_retries_and_safe_errors、test_timeout_no_blind_retry | 通過 |
| Minimal demonstrable interface／Model unavailable | test_web::test_generation_unavailable_is_understandable（逾時顯示暫時無法生成＋查詢識別碼，下一請求正常） | 通過 |
| Specific process identity support／General evidence cannot identify a special form | test_answering 表單識別守衛；開發 D15 employee 回資料不足 | 通過 |
| Server derived citation union／Empty supported claims、Unknown claim or obsolete duplicate summary | test_openai_provider、test_answering::test_citation_whitelist_checks_even_unused_answer_citations | 通過 |
| Verbatim evidence selection candidate／Selected paragraph preserves limitations | test_verbatim::test_verbatim_preserves_whole_authorized_text 等9項；正式採用見 stage-5-acceptance.md | 通過 |

## evaluation-observability

| Requirement／Scenario | 證據 | 結果 |
|---|---|---|
| Measure context precision and evidence coverage／Relevant evidence plus noise | test_evaluation::test_precision_errors_empty_missing_and_merged_sources；開發 82.14%、保留 100%（使用者標註38項） | 通過 |
| Reconstruct the actual model exchange／Replay after a source update | test_audit::test_end_to_end_replay_survives_source_update、test_replay_after_source_update_uses_saved_input、test_purge_default_retention_and_explicit_before | 通過 |
| Close the feedback loop／Resolve a reported citation issue | test_feedback（7項）；實例 feedback bb50b50c：回報→分析→修正→回歸JUnit→已修正（stage-6.md） | 通過 |
| Local actionable anomaly alerts／Threshold and recovery | test_monitoring（10項，含真實防線注入） | 通過 |
| Holdout freeze before retrieval tuning／Deferred holdout format repair | eval/baseline.freeze.json；stage-1-resume.md | 通過 |
| Human reviewed evaluation set／Split before tuning | 20／10，分配 6/5/3/3/3 與 4/3/1/1/1；test_evaluation_schema | 通過 |
| ／Permission question per role | 開發 9/9；**保留 2/3（H09 employee 狀態不符）** | **未通過** |
| ／Holdout outside the workspace | test_evaluation_schema::test_holdout_inside_project_rejected_before_read、test_symlink_into_project_is_rejected；test_holdout::test_holdout_file_must_be_external_and_hash_matched | 通過 |
| Explicit release thresholds／Compute citation scores | 答案 22/22（保留 8/8）、引用 53/53、覆蓋 38/38、資料不足 4/4、版本 4/4；test_answer_review、test_holdout | 通過 |
| Expand authorization tests／Release veto | 12次授權執行 11/12；自動測試（冒充、直接引用、撤回、跨帳號）全過 | **未通過（否決）** |
| Trace and compare runs／Audit an answer | test_audit::test_query_trace_is_restricted_and_event_has_only_ids、test_unknown_cost_and_usage_are_null_not_zero、test_credentials_are_never_saved | 通過 |
| Honest experiment report／Holdout exposure | 開發／保留分列、三模式、6 vs 10 份（stage-7-official.md）、硬體、延遲、費用、失敗與修正（README、stage-5～7）。保留題結果已看過，但未據以修改；草擬者與後期實作者同為 Claude，已揭露 | 通過 |

## 三項能力演示（瀏覽器，stage-6.md）

1. **官方依據與引用：** employee 問婚假，答「婚假十四日、工資照給」，附勞工請假規則 §2 原文。
2. **公司流程與來源區分：** manager 問特殊覆核，答 C03 橙色覆核單 M-17，並分開標示 C01 的「不得因內部表單否定法定請假」。
3. **檢索前權限過濾：** 同一題 D16，hr 取得 C04 紫杉異常簿 H-42；employee 只得到資料不足與公開 C01 背景，無 C04 標題或內容。

## 7.4 乾淨環境重建

依 README 在全新 `.runtime/stage7-clean-venv` 執行：`py -3.12 -m venv` → `uv pip sync requirements.lock --require-hashes` → `pip install -e .` → `pip check`（No broken requirements）→ `scripts/download_models.py`（依鎖定 revision 核對既有模型）→ `pytest -q`：**494 passed、1 Windows symlink 權限 skip**（225.52 秒，`reports/stage7-clean-env-tests.xml`，紀錄 `.runtime/stage7-clean-env.log`）。重建的是 Python 環境；語料索引沿用既有 `.runtime/corpus`，沒有從零重新匯入。凍結核對前後皆 64 檔一致。

## 費用與紀錄

全專案 461 次 API、估算 US$0.9392692（上限 US$1，含所有失敗與診斷）。無 Git 版本庫；可重現性依 requirements.lock、eval/final.freeze.json 與各階段報告。

## 驗收後介面補充（2026-10-19）

應使用者要求，提問頁加入每角色兩題開發集示範問題（點選只填入、不自動送出）並預設當天日期。只改 `web.py`、`home.html`、`app.css`，並在規格新增 Scenario「Role sample questions」。原凍結移至 `eval/history/final.freeze.2026-10-19-v1.json`（`ea94e472…`，保留題結果在此凍結下產生）；新凍結 `eval/final.freeze.json`（`7e1c9693…`）記錄supersedes、變更檔案與原因，生成設定與語料指紋相同。完整測試 498 passed／1 skip（`reports/stage7-ui-presets-tests.xml`）。驗收結論不變。

## 介面改版（2026-10-19）

使用者確認草稿（`docs/ui-mockup.html`）後改為側欄＋底部提問列版面，新增本人查詢紀錄頁。凍結v2移至 `eval/history/final.freeze.2026-10-19-v2.json`，目前 `eval/final.freeze.json`（`f2640e77…`，65檔）；生成設定與語料指紋不變。完整測試 501 passed／1 skip（`reports/stage7-ui-redesign-tests.xml`）。驗收結論不變。

## 公開前整理（2026-10-19）

移除本機使用者目錄：保留題位置改由 `HR_RAG_HOLDOUT_PATH` 或 `%LOCALAPPDATA%` 通用路徑提供，hash 核對不變。凍結v3移至 `eval/history/`，目前 `eval/final.freeze.json`（`561676be…`）。完整測試 502 passed／1 skip（`reports/stage7-publish-prep-tests.xml`）。驗收結論不變。
