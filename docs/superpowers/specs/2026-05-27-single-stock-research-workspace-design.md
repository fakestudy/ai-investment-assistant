# 单股研究工作区 v1 设计方案

## 1. 产品定位

这个产品不是 AI 聊天助手，也不是 AI 选股器，而是一个个人美股研究工作台。它围绕单只股票的投资假设展开：先帮用户基于财报、SEC 文件和新闻生成 thesis 草稿，用户确认后，系统持续把新资料转成研究笔记，并判断这些资料是在支持、削弱还是触发复盘。

第一版优先解决单股深度研究，不急着做自选股批量巡检。AI 对话是股票或研究笔记上的追问能力，不作为主入口。系统不提供买入、卖出、加仓、减仓、仓位、目标价等交易建议，也不做飞书推送、券商接入和真实登录 UI。

核心目标：

- 让用户清楚记录“我为什么关注这只股票”。
- 让财报、SEC 文件和新闻被整理成可复用的研究资料。
- 让新资料自动和原 thesis 对齐，判断它支持、削弱还是触发复盘。
- 让 AI 输出始终带来源和研究边界，不替用户做交易决策。

## 2. v1 范围

### 包含

- 单用户本地工作台。
- 数据模型保留 `user_id`，但前端不做登录 UI，默认使用本地用户。
- 输入 ticker 后创建单股研究工作区。
- 接入或导入财报、SEC 文件、财报摘要、相关新闻。
- AI 基于资料生成 thesis 草稿。
- 用户编辑或确认 thesis 后，thesis 才正式生效。
- thesis 必须包含失效条件 `invalidated_if`。
- AI 生成双层 Research Note：短卡片和可展开长报告。
- AI 生成 Thesis Check：判断新资料支持、削弱、中性或触发复盘。
- 站内按 P0-P3 展示重要性。
- AI 追问只挂在股票或研究笔记上下文里。

### 不包含

- 买入、卖出、加仓、减仓、仓位建议。
- 自动交易、券商接入、真实持仓同步。
- AI 选股排行榜、AI Score、目标价预测。
- 批量自选股巡检。
- 飞书/Lark 推送或其他外部推送。
- 完整多用户认证。
- 泛新闻流。
- 行情面板优先体验。

## 3. 核心体验

v1 主流程是“单股研究工作区”，不是 dashboard 优先。

### 进入工作台

用户输入或选择一个 ticker。系统进入该股票的研究工作区。

- 如果这是第一次研究该股票，先进入 thesis 初始化流程。
- 如果已有 thesis，直接展示当前研究状态。

### Thesis 初始化

系统基于公司基础信息、最近财报、SEC 文件和相关新闻生成 thesis 草稿。草稿不能直接生效，必须由用户编辑或确认。

正式 thesis 包含：

- `why_interested`：为什么关注这只股票。
- `core_belief`：核心判断。
- `key_drivers`：支持判断的关键驱动。
- `risk_factors`：主要风险因素。
- `watch_indicators`：后续观察指标。
- `time_horizon`：研究周期。
- `status`：观察中、已建立观点、需要复盘、已放弃。
- `invalidated_if`：如果发生这些情况，原判断失效或必须重新复盘。

### 资料整理

系统把财报、SEC 文件、财报摘要和新闻整理成资料条目。每条资料保留来源、发布时间、数据类型、摘要和原文链接。

新闻只作为补充事件源，不做泛信息流。

### Research Note

AI 从资料生成双层研究笔记：

- 短卡片：一屏内展示结论、关键证据、反方证据、对 thesis 的影响、后续观察。
- 长报告：展开后展示业务变化、财务变化、管理层表述、风险、估值或预期影响、来源引用。

每篇 Research Note 都必须说明它对 thesis 的影响：

- 支持。
- 削弱。
- 中性。
- 触发复盘。

### Thesis Check

当新资料进入时，系统生成一次 Thesis Check：

- 是否命中 `invalidated_if`。
- 是否改变关键驱动。
- 是否强化或削弱核心判断。
- 是否需要用户复盘。
- 重要性等级：P0、P1、P2、P3。

P0-P3 只用于站内排序和视觉提示，不触发外部推送。

### Ask AI

AI 对话只出现在股票页和研究笔记里，用来追问当前资料、当前 thesis 或某条结论。它不是一级入口，也不承担泛金融聊天功能。

## 4. 页面结构

### `/`

本地单用户工作台入口。

- 展示最近研究的股票。
- 提供添加 ticker 的入口。
- 不做复杂 dashboard。
- 不做登录页。

### `/stocks/[symbol]`

单股研究工作区，是 v1 核心页面。

页面分区：

- `Thesis`：当前正式 thesis，支持编辑。
- `Research Notes`：研究笔记列表，默认短卡片，可展开长报告。
- `Sources`：财报、SEC 文件、财报摘要、新闻等资料。
- `Thesis Checks`：资料对 thesis 的影响判断。
- `Ask`：基于当前股票、thesis、资料和研究笔记的追问。

### 后续页面

`/watchlist` 留到 v2，用于把单股研究链路扩展成自选股批量巡检。

## 5. 数据模型

核心数据模型围绕“研究状态”设计，不围绕聊天设计。

### `users`

保留用户模型。v1 默认创建或使用一个本地用户。

### `stocks`

保存股票基础信息：

- symbol。
- company_name。
- exchange。
- currency。
- sector。
- industry。

### `research_workspaces`

表示某个用户对某只股票的研究工作区。

关键字段：

- user_id。
- stock_id。
- status。
- created_at。
- updated_at。

### `investment_theses`

保存正式 thesis。

关键字段：

- research_workspace_id。
- why_interested。
- core_belief。
- key_drivers。
- risk_factors。
- watch_indicators。
- time_horizon。
- status。
- invalidated_if。
- source_note。
- created_at。
- updated_at。

### `source_documents`

保存原始资料元数据和可追溯内容。

关键字段：

- research_workspace_id。
- source_type：earnings_release、sec_filing、transcript_summary、news。
- title。
- published_at。
- source_url。
- provider。
- raw_content_ref。
- summary。
- created_at。

### `research_notes`

保存双层研究笔记。

关键字段：

- research_workspace_id。
- source_document_ids。
- short_summary。
- conclusion。
- key_evidence。
- counter_evidence。
- thesis_impact：support、weaken、neutral、review_required。
- watch_indicators。
- long_report。
- citations。
- disclaimer。
- created_at。

### `thesis_checks`

保存新资料对 thesis 的影响判断。

关键字段：

- research_workspace_id。
- investment_thesis_id。
- source_document_id。
- impact：support、weaken、neutral、review_required。
- priority：P0、P1、P2、P3。
- invalidated。
- invalidation_reason。
- changed_drivers。
- reasoning。
- citations。
- created_at。

### `ai_chat_messages`

保存追问记录。它必须挂在明确上下文下。

关键字段：

- research_workspace_id。
- research_note_id，可为空。
- source_document_id，可为空。
- role。
- content。
- citations。
- created_at。

## 6. AI 工作流

### `GenerateThesisDraft`

输入：

- ticker。
- 公司基础信息。
- 一组 source documents。

输出：

- thesis 草稿。
- 关键依据。
- 风险因素。
- 观察指标。
- 失效条件建议。
- 引用来源。

约束：

- 输出不能直接成为正式 thesis。
- 必须由用户编辑或确认。
- 不允许包含交易指令。

### `GenerateResearchNote`

输入：

- 当前 thesis。
- 一组 source documents。

输出：

- 短卡片。
- 长报告。
- 对 thesis 的影响。
- 关键证据。
- 反方证据。
- 后续观察指标。
- 引用来源。
- 免责声明。

约束：

- 必须区分事实、推理和不确定性。
- 必须保留引用来源。
- 不允许输出买卖建议。

### `CheckThesisImpact`

输入：

- 当前正式 thesis。
- 新 source document。

输出：

- impact：support、weaken、neutral、review_required。
- priority：P0、P1、P2、P3。
- 是否命中 `invalidated_if`。
- 命中原因。
- 受影响的关键驱动。
- 需要继续观察的指标。
- 引用来源。

约束：

- 如果命中 `invalidated_if`，必须输出 `review_required`。
- 不确定时宁可输出需要复盘，也不要伪造确定性。

### `AnswerResearchQuestion`

输入：

- 用户问题。
- 当前股票。
- 当前 thesis。
- 相关 source documents。
- 相关 research notes。

输出：

- 回答。
- 引用来源。
- 不确定性说明。
- 免责声明。

约束：

- 只能围绕当前研究上下文回答。
- 不作为泛金融聊天入口。

## 7. 系统边界

前端仍只通过 HTTP 调用 Go BFF。Go 后端负责用户、股票、资料、thesis、research note、thesis check、聊天记录等业务数据落库。

Python Agent Service 只负责 AI 分析和结构化输出。Go 与 Python 之间通过 protobuf RPC 通信。

建议 Agent RPC：

- `GenerateThesisDraft(GenerateThesisDraftRequest) returns (ThesisDraftResult)`。
- `GenerateResearchNote(GenerateResearchNoteRequest) returns (ResearchNoteResult)`。
- `CheckThesisImpact(CheckThesisImpactRequest) returns (ThesisCheckResult)`。
- `AnswerResearchQuestion(AnswerResearchQuestionRequest) returns (AnswerResearchQuestionResult)`。

Go 后端不能依赖 LangGraph 内部实现，只依赖 protobuf 契约。Python 侧可以持续调整 graph 节点、Prompt、工具和模型 provider，只要 RPC schema 稳定，就不会破坏业务服务。

## 8. 事件优先级

v1 保留站内优先级，不做外部推送。

- `P0`：可能触发 thesis 失效条件，必须复盘。
- `P1`：明显影响核心驱动或风险因素，建议查看。
- `P2`：有信息价值，但短期不改变判断。
- `P3`：噪音或弱相关，默认折叠。

## 9. 研究边界

所有 AI 输出必须遵守以下边界：

- 不输出买入、卖出、加仓、减仓、仓位建议。
- 不输出确定性收益承诺。
- 不把模型推理伪装成事实。
- 不隐藏来源。
- 不隐藏不确定性。
- 必须展示“仅供研究参考，不构成投资建议”。

## 10. 验收标准

- 输入一只股票后，可以创建单股研究工作区。
- 系统可以基于财报、SEC 文件、财报摘要或新闻生成 thesis 草稿。
- 用户确认 thesis 后，系统能保存正式 thesis。
- 正式 thesis 包含 `invalidated_if`。
- 导入或抓取一组资料后，系统能生成 Research Note。
- Research Note 短卡片能在一屏内回答：结论、证据、反证、对 thesis 的影响、后续观察。
- 展开长报告能看到更完整的业务、财务、风险和来源引用。
- 新资料进入后，系统能生成 Thesis Check。
- Thesis Check 能判断是否触发 `invalidated_if`。
- AI 追问能带入当前股票、thesis、资料和研究笔记上下文。
- 所有 AI 输出带来源和研究边界。

## 11. 后续扩展

v2 再考虑：

- 自选股批量巡检。
- Today Briefing。
- 飞书/Lark 推送。
- 邮箱登录和白名单。
- 更完整的数据 provider。
- 持仓导入，但仍不做自动交易。
- 更细的财务指标和估值模型。
