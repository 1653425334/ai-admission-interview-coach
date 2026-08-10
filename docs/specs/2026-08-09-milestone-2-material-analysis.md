# Milestone 2：证据驱动的面试地图规格

**状态：** 待产品确认（第二版）
**日期：** 2026-08-09
**依赖：** Milestone 1 已完成并通过真实 Supabase A/B 用户验收
**目标用户：** 准备 AI/CS 研究生申请面试的申请人

## 1. 产品判断与修订结论

M2 不以“生成一份材料总结报告”为成功。普通 ChatGPT 已能完成摘要、润色和泛化问题列表；如果系统只展示候选人画像和风险说明，就没有形成可持续的训练价值。

M2 的核心产物改为版本化、证据可追溯、可被面试引擎执行的 `InterviewMap`。完整训练闭环为：

```text
材料证据 → 候选人主张 → 面试风险 → 可验证目标 → 覆盖条件 → 问题
         → 回答 → 评价 → 目标/风险状态更新 → 下一道问题
```

M2 负责闭环左半段，止于 `InterviewMap`；Answer Evaluation、多轮动态追问和 Risk State Update 属于 M3。本规格同时冻结 M3 将消费的最小运行时契约，用纵向示例证明地图可执行，但不实现 M3。

本次相对初稿的关键修订：

- 将 `CandidateProfile + RiskReport` 的展示结果升级为可执行的 `InterviewMap`；
- 将自由文本 `interview_objective` 拆成独立、可验证的 `Objective` 和 `CoverageCondition`；
- 每项风险必须包含原文证据、关联主张、目标、覆盖条件、建议问题类型、最大追问次数和初始验证状态；
- V1 风险类别收敛为五类，避免分类体系先于真实案例膨胀；
- M2 不预生成正式问题文本，避免问题脱离候选人的实时回答；
- 增加与普通 ChatGPT 的五案例成对回归评测；
- 后台任务、解析预览和成本记录只保留为支撑纵向闭环的必要能力。

## 2. M2 目标、非目标与阶段边界

### 2.1 M2 必须实现

- 从私有 Storage 下载并逐页解析当前 CV 与 PS；
- 从原文提取少量高价值、可被面试验证的 Candidate Claim；
- 识别值得面试验证的风险，而不是为了数量制造风险；
- 为每条风险建立至少一个可执行 Objective 及明确 Coverage Conditions；
- 输出并持久化 `interview-map-v1`，供 M3 原样绑定和消费；
- 对 Schema、引用关系、页码和原文摘录做确定性校验；
- 使用 Fake LLM 完成日常开发、自动化测试和回归；
- 仅用少量真实调用验收地图质量，并受硬预算保护；
- 提供极简状态与结果 UI：Candidate Overview 和按优先级排列的 Interview Map。

### 2.2 M2 只设计并冻结、不执行

- `Question`、`Evaluation` 和 Verification Status 转换契约；
- 一条风险的 2–3 轮动态追问纵向示例；
- M2→M3 回归夹具、基线协议和成功门槛。

这些契约在 M2 确认后视为跨里程碑接口；M3 不得用自由 JSON 绕过。

### 2.3 明确延后

- 真正的多轮面试、回答评价、风险动态更新和整场报告；
- 完整 8–12 轮、多风险调度；
- 语音、视频、OCR、Word、RAG、向量库；
- GitHub、源码压缩包、报告、Slides 和实验结果分析；
- 学校官网抓取、录取概率、CV/PS 自动修改；
- 复杂知识图谱、通用工作流引擎和 Multi-Agent 框架；
- 大型 Dashboard、复杂图表和历史版本对比；
- 实时 Token 计价账单系统。

## 3. 当前实现评审与复用原则

### 3.1 直接复用

- Next.js Web、FastAPI API、独立 Worker 的模块化单体方向；
- Supabase Auth、服务端 JWT 验证和统一 `404` 的所有权边界；
- PostgreSQL 作为领域状态与任务状态的唯一事实源；
- 私有 Supabase Storage 及 `ObjectStorage` 抽象；
- `applications` 与每个申请最多一份 CV、一份 PS 的约束；
- `documents` 已有的 `sha256`、`parse_status`、`extracted_text`、`parse_error`；
- M1 的错误 envelope、request ID、上传限制和 PDF 验证；
- 后端拥有领域表，前端只直接使用 Supabase Auth 的架构原则。

### 3.2 需要增量修改

- `ObjectStorage` 增加私有对象读取能力；
- `documents` 增加 `parsed_at`、`parser_version`、`page_count`；
- 新增 `analysis_runs`、`jobs`、`llm_runs`；
- 新增 InterviewMap Pydantic Schema、校验器、Fake/真实 provider adapter；
- 新增分析 API、解析预览 API 和极简结果页；
- 删除/替换文档时使关联分析失效，并按最终隐私决策清理派生数据。

### 3.3 不重新建设

- 不改为 Next.js-only 后端；
- 不绕过 FastAPI 让前端直接访问领域表或 Storage；
- 不引入 Redis、Celery、Kafka、LangChain、Dify 或多 Agent 服务；
- 不重写 M1 已验收的鉴权、上传和用户隔离路径；
- 不为未来 Project Artifact Vault 提前创建代码索引或向量基础设施。

## 4. 用户体验

1. 用户在申请详情页上传 CV 与 PS，并启动材料分析。
2. API 创建不可变输入快照和分析记录，返回 `202 Accepted`。
3. Worker 解析材料并生成 `InterviewMap`；刷新页面后仍可恢复状态。
4. 完成页展示简短 Candidate Overview，用户可发现明显解析错误。
5. 页面主体按优先级展示风险，而不是长篇材料摘要。
6. 每条风险展示标题、严重程度、原文证据、值得验证的原因、Objective、最大追问次数和 `UNVERIFIED` 状态。
7. 后续进入 M3 时，Interview Session 永久绑定 `analysis_run_id` 与 `schema_version`。

风险文案必须是“需要面试确认的假设”，不得把模型判断写成候选人的真实缺陷。例如使用“材料尚未说明个人负责部分”，而不是“候选人没有实际贡献”。

## 5. 核心领域模型

所有 AI 产物使用 Pydantic 定义并生成 JSON Schema。LLM 必须返回 Structured Output；数据库只接受 Schema 与应用层不变量均通过的完整对象。

### 5.1 SourceLocation

```json
{
  "page_number": 1,
  "section": "Projects",
  "start_offset": 420,
  "end_offset": 486
}
```

- `page_number` 是当前 PDF 解析能力下的强定位信息；
- `section` 是可空的模型辅助标签，不作为证据真实性依据；
- offset 指向该页规范化文本，可空；若存在必须与 original text 匹配；
- 将定位封装为对象，为未来 Project Artifact Vault 支持文件路径、代码行或幻灯片页保留扩展空间，但 M2 不实现这些来源。

### 5.2 Evidence

```json
{
  "evidence_id": "ev-001",
  "source_type": "APPLICATION_DOCUMENT",
  "document_id": "uuid",
  "document_type": "CV",
  "location": {
    "page_number": 1,
    "section": "Projects",
    "start_offset": 420,
    "end_offset": 486
  },
  "original_text": "Developed an attention-based model to improve robustness."
}
```

不变量：

- `source_type` 在 M2 只能是 `APPLICATION_DOCUMENT`；
- `document_id` 必须属于本次不可变输入快照；
- `document_type` 只能是 `CV | PS`，且必须与数据库一致；
- 规范化空白后，`original_text` 必须能在对应页精确定位；
- 原文不得由模型改写，单条不超过 300 字符；
- 单次地图内 `evidence_id` 唯一，其他对象只引用 ID；
- Risk 不得引用地图之外的 Evidence。

`source_type + location` 是为未来 artifact 扩展保留的最小接口，不新增通用 Artifact 表或多态数据库模型。

### 5.3 CandidateClaim

```json
{
  "claim_id": "claim-001",
  "category": "PERFORMANCE_IMPROVEMENT",
  "statement": "The proposed attention-based method improved robustness.",
  "assertion_strength": "EXPLICIT",
  "evidence_ids": ["ev-001"],
  "interview_value": "HIGH"
}
```

`category`：

`TECHNICAL_CHOICE | PROJECT_CONTRIBUTION | METHOD_INNOVATION | PERFORMANCE_IMPROVEMENT | RESEARCH_CONCLUSION | PERSONAL_OWNERSHIP | MOTIVATION`

`assertion_strength`：

- `EXPLICIT`：材料直接陈述；
- `IMPLIED`：可合理归纳，但原文没有完整陈述；
- `CONFLICTING`：材料对同一命题存在冲突。

只保留 `interview_value=HIGH` 的高价值主张。学历、日期、技能名称等普通事实不应全部变成 Claim；它们可进入 CandidateProfile 的轻量上下文。每条 Claim 至少引用一项 Evidence。缺少材料依据的内容不得成为 Claim。

### 5.4 CoverageCondition

```json
{
  "condition_id": "cond-001",
  "type": "NAMES_TEST",
  "description": "Names the robustness or perturbation test used.",
  "required": true
}
```

Coverage Condition 描述“回答中必须出现什么可观察信息”，是本产品区别于泛化追问的关键。

V1 `type`：

`NAMES_TEST | EXPLAINS_BASELINE | PROVIDES_RESULT | EXPLAINS_MECHANISM | JUSTIFIES_CHOICE | DISTINGUISHES_OWNERSHIP | RESOLVES_INCONSISTENCY | CONNECTS_MOTIVATION_TO_EXPERIENCE`

条件必须能被 M3 判断为 `MET | NOT_MET | UNCLEAR`，不得写成“充分展示能力”“回答得很好”等不可验证措辞。

### 5.5 VerificationObjective

```json
{
  "objective_id": "obj-001",
  "risk_id": "risk-001",
  "target_claim_id": "claim-001",
  "verification_goal": "验证候选人能否解释 robustness 的定义、评测方法、baseline 和具体结果。",
  "coverage_conditions": [
    {
      "condition_id": "cond-001",
      "type": "NAMES_TEST",
      "description": "Names the robustness or perturbation test used.",
      "required": true
    },
    {
      "condition_id": "cond-002",
      "type": "EXPLAINS_BASELINE",
      "description": "Explains the baseline used for comparison.",
      "required": true
    },
    {
      "condition_id": "cond-003",
      "type": "PROVIDES_RESULT",
      "description": "Provides a concrete comparison or result.",
      "required": true
    }
  ]
}
```

不变量：

- 一个 Objective 只验证一个清晰命题；
- 至少一个 Coverage Condition，且至少一个为 `required=true`；
- Objective 必须绑定同一 Risk 的 Claim；
- 目标描述应说明“验证候选人是否能解释/区分/证明什么”，不能直接诊断能力；
- M2 不在 Objective 内生成固定问题文本。

### 5.6 InterviewRisk

```json
{
  "risk_id": "risk-001",
  "category": "EVIDENCE_GAP",
  "title": "Robustness improvement lacks evaluation evidence",
  "severity": 4,
  "evidence_ids": ["ev-001"],
  "claim_id": "claim-001",
  "reason": "The material claims improved robustness but gives no test, baseline, or result.",
  "objectives": [],
  "suggested_question_types": ["EVIDENCE_PROBE", "TECHNICAL_DEPTH_PROBE"],
  "max_followups": 2,
  "verification_status": "UNVERIFIED"
}
```

V1 风险类别只允许：

- `TECHNICAL_UNDERSTANDING`：材料无法体现候选人对所用方法、机制或取舍的理解；
- `OWNERSHIP`：团队成果与个人职责边界不清；
- `EVIDENCE_GAP`：重要主张缺少 baseline、方法、指标或具体结果；
- `CONSISTENCY`：CV、PS 或材料内部存在需要解释的冲突；
- `MOTIVATION_DEPTH`：强烈动机缺少具体经历、选择依据或行动支持。

`suggested_question_types`：

`EVIDENCE_PROBE | OWNERSHIP_PROBE | TECHNICAL_DEPTH_PROBE | CONSISTENCY_PROBE | MOTIVATION_PROBE | TRADEOFF_PROBE | REFLECTION_PROBE`

不变量：

- 每项 Risk 至少引用一条 Evidence、一个 Claim 和一个 Objective；
- Risk 的 Evidence 必须与 Claim Evidence 有交集；
- `severity` 为 `1..5`，仅决定训练优先级，不表示录取概率；
- `max_followups` 指初始问题后的最大追问数，只能是 `0..2`；
- M2 输出的 `verification_status` 永远是 `UNVERIFIED`；
- 风险允许为 0 条，通常目标 3–8 条，不得凑数；
- Reason 描述为何值得面试验证，不得断言候选人撒谎或能力不足。

### 5.7 VerificationStatus

跨 M2/M3 稳定枚举：

`UNVERIFIED | PARTIALLY_VERIFIED | VERIFIED | CONFIRMED_RISK`

- `UNVERIFIED`：尚未通过回答验证；M2 唯一允许的初始值；
- `PARTIALLY_VERIFIED`：部分 required conditions 已满足，但仍有缺口；
- `VERIFIED`：全部 required conditions 已通过回答覆盖，风险在本次训练中被消除；
- `CONFIRMED_RISK`：追问预算耗尽后关键条件仍明确不满足，风险在本次训练中仍成立。

若回答无法判断而非明确不满足，M3 应停留在 `UNVERIFIED` 或 `PARTIALLY_VERIFIED`，不能用 `CONFIRMED_RISK` 假装确定性。具体状态转换由 M3 的不可变 Evaluation 事件确定性重放，模型不能直接写最终状态。

### 5.8 CandidateProfile

```json
{
  "summary": "Candidate focused on robust machine learning for healthcare.",
  "education_summary": "...",
  "experience_summary": "...",
  "research_interests": ["robust machine learning", "healthcare AI"],
  "high_value_claim_ids": ["claim-001"],
  "missing_or_uncertain_information": ["No evaluation dataset is named."]
}
```

CandidateProfile 是用户发现解析错误和理解风险上下文的辅助视图，不是 M2 的核心价值。Summary 不得引入 Claim/Evidence 之外的新事实。

### 5.9 InterviewMap

```json
{
  "schema_version": "interview-map-v1",
  "analysis_run_id": "uuid",
  "input_manifest": [
    {
      "document_id": "uuid",
      "document_type": "CV",
      "sha256": "hex",
      "page_count": 2
    }
  ],
  "candidate_profile": {},
  "evidence": [],
  "claims": [],
  "risks": [],
  "priority_risk_ids": ["risk-001"]
}
```

`InterviewMap` 是 analysis run 的单一权威产物。`priority_risk_ids` 是训练优先级，不是固定问题列表。排序优先考虑 severity，再考虑跨文档冲突和可验证性；同分使用稳定 ID 排序。

## 6. M2→M3 最小纵向切片

M2 不实现以下流程，但必须证明其地图无需字段猜测即可驱动它。

### 6.1 M2 输入与输出

CV Evidence：

> Developed an attention-based model to improve robustness.

M2 抽取：

- Claim：`The proposed method improved robustness.`
- Risk：`EVIDENCE_GAP`
- Objective：验证候选人能否解释 robustness 如何定义和评估；
- Conditions：
  - names the robustness/perturbation test；
  - explains the baseline；
  - provides a concrete comparison/result；
- SuggestedQuestionTypes：`EVIDENCE_PROBE`, `TECHNICAL_DEPTH_PROBE`；
- MaxFollowups：2；
- VerificationStatus：`UNVERIFIED`。

### 6.2 M3 运行时契约示例

`Question-v1`：

```json
{
  "question_id": "uuid",
  "risk_id": "risk-001",
  "objective_id": "obj-001",
  "question_type": "EVIDENCE_PROBE",
  "target_condition_ids": ["cond-001", "cond-002", "cond-003"],
  "text": "你如何定义和测试这里的 robustness？使用了什么 baseline，结果如何？",
  "followup_index": 0,
  "parent_question_id": null
}
```

`Evaluation-v1`：

```json
{
  "question_id": "uuid",
  "risk_id": "risk-001",
  "objective_id": "obj-001",
  "condition_results": [
    {
      "condition_id": "cond-001",
      "result": "MET",
      "answer_excerpt": "we tested Gaussian noise and missing features",
      "reason": "The answer names concrete perturbation tests."
    },
    {
      "condition_id": "cond-002",
      "result": "UNCLEAR",
      "answer_excerpt": null,
      "reason": "No baseline is identified."
    },
    {
      "condition_id": "cond-003",
      "result": "UNCLEAR",
      "answer_excerpt": null,
      "reason": "No concrete comparison is provided."
    }
  ],
  "unmet_required_condition_ids": ["cond-002", "cond-003"],
  "followup_recommended": true
}
```

### 6.3 2–3 轮决策

1. Q1 同时探测测试、baseline 和结果。
2. 用户只说测试方法；Evaluation 标记 `cond-001=MET`，其余 `UNCLEAR`。
3. Q2 只能针对未满足条件追问 baseline 和具体结果，不能重复“请详细说明 robustness”。
4. 若 Q2 给出 baseline 但仍无数值，则更新为 `PARTIALLY_VERIFIED`，还有一次追问预算。
5. Q3 只追问 concrete comparison/result；之后必须停止。
6. 全部 required conditions 满足 → `VERIFIED`；部分满足 → `PARTIALLY_VERIFIED`；关键条件被明确否认且预算耗尽 → `CONFIRMED_RISK`；完全无法判断可保持 `UNVERIFIED`。

每个 condition 的当前结果取 Evaluation 事件序列中最后一次对它的判断；未在本轮判断的 condition 保留原结果。Evaluation 只追加、不覆盖，以便重放相同 turns 得到相同状态。

### 6.4 纵向切片验收要求

- 每一问都可追溯到同一 Risk、Objective 和具体 Condition；
- Q2/Q3 利用上一轮 Evaluation，而非预生成问题列表；
- 后端限制最多两次追问；
- answer excerpt 可在对应回答中定位；
- 状态由确定性函数计算，LLM 只判断 condition；
- 刷新后恢复唯一未回答问题，不重复生成或计费；
- 完整路径使用 Fake LLM 进入 M3 CI，真实模型只做少量手工验收。

## 7. 产品差异化回归评测

### 7.1 评测问题

评测不试图证明全面击败 ChatGPT，而验证结构化流程是否更稳定地产生“有证据、可验证、可驱动后续动态面试”的输出。

### 7.2 五个固定案例

1. **Missing baseline**：材料声称性能提升但没有 baseline；Gold Risk 为 `EVIDENCE_GAP`。
2. **Led project ambiguity**：CV 写 led project，PS 只描述团队工作；Gold Risk 为 `OWNERSHIP`，可附次要 `CONSISTENCY`。
3. **Complex model, shallow explanation**：使用 attention/Transformer 等复杂模型但材料无法体现原理；Gold Risk 为 `TECHNICAL_UNDERSTANDING`。
4. **Unsupported motivation**：强烈 AI/Healthcare 动机但没有对应经历或行动；Gold Risk 为 `MOTIVATION_DEPTH`。
5. **Cross-document contradiction**：CV/PS 对同一经历的角色、结果或时间描述矛盾；Gold Risk 为 `CONSISTENCY`。

每例人工维护：输入 CV/PS、Gold Evidence、Gold Claim、Gold Risk、可接受的 Objective、required Coverage Conditions，以及“不应生成”的 unsupported risks。至少一例包含材料内 prompt injection，验证其只被当作数据。

### 7.3 公平基线

- Baseline：相同模型读取相同 CV/PS，使用冻结通用提示词：“分析这位申请人的材料，识别面试风险并生成针对性问题”；
- Product：相同模型、相同材料，通过 Evidence → Claim → Risk → Objective → InterviewMap Structured Output；
- 模型版本、温度、语言和输出预算一致；
- 去除产品标签后盲评；
- Fake fixtures 每次 CI 执行契约回归，真实成对评测仅在发布候选阶段按预算运行。

### 7.4 指标定义

- `Gold risk recall`：Gold Risks 中被正确识别的比例；
- `Evidence grounding accuracy`：输出 Risk 的证据引用可定位且支持该 Risk 的比例；
- `Unsupported risk rate`：没有输入证据或不在合理 Gold 范围内的风险比例；
- `Objective verifiability`：Objective 含可观察 Coverage Conditions、可由回答判定的比例；
- `Generic question rate`：可不修改地用于任意候选人的泛化问题比例；M2 以 suggested type/objective 模拟评审，M3 再评正式问题；
- `Schema validity`：首次输出通过 JSON Schema 和领域不变量的比例。

### 7.5 V1 成功门槛

- Schema validity：100%；
- Evidence 定位有效率：100%；
- Gold risk recall：≥80%；
- Evidence grounding accuracy：≥90%；
- Unsupported risk rate：≤10%；
- Objective verifiability：≥90%；
- Generic question rate：比 Baseline 至少低 30%；
- 五例中至少四例，Product 在“可驱动后续面试”盲评维度不低于 Baseline。

如果未达到门槛，优先修改 Evidence/Claim 选择、Coverage Condition 质量或 Prompt，不扩展 UI、风险类别或基础设施。

## 8. 分析状态机

`analysis_runs.status`：`PENDING | RUNNING | COMPLETED | FAILED`。

`analysis_runs.stage`：`QUEUED | PARSE_DOCUMENTS | BUILD_INTERVIEW_MAP | COMPLETED | FAILED`。

用户只看到“排队、解析材料、生成面试地图、完成/失败”。Claim extraction 与 Risk construction 可以是内部 LLM operation，不暴露为复杂产品流程。

核心规则：

- 完整分析要求同一申请当前同时存在一份 CV 和一份 PS；
- 同一输入 manifest 最多一个活跃分析；
- 主动重跑创建新 run，不覆盖旧结果；
- 写结果前重新确认文档 ID 与 SHA-256，否则 `ANALYSIS_INPUT_CHANGED`；
- 旧地图与当前文档快照不匹配时不得显示为当前，也不得创建新 Session；
- Worker 只在领取 job 的短事务内持锁，模型调用期间不持数据库锁。

## 9. PDF、证据与安全

- 沿用 M1 的 10 MiB、30 页、PDF 签名及文本型 PDF 限制；
- 后端从私有 Storage 读取，读取前执行所有权检查；
- 使用本地库逐页提取，不把原 PDF 上传给模型；
- 规范化换行、空字符和行内重复空白，保留页码与段落顺序；
- `documents.extracted_text` 保存带页边界的内部格式；
- 无有效文本返回 `EMPTY_EXTRACTED_TEXT`，扫描件提示上传可选择文字的 PDF；
- 材料标记为 `UNTRUSTED_DOCUMENT_DATA`，其中命令、角色和 Schema 修改均不执行；
- LLM 调用不开工具、网络、文件搜索或其他用户数据；
- 常规日志不写全文、Prompt、原始响应、Evidence、Storage key 或密钥。

## 10. AI 边界与成本策略

```python
class InterviewMapLLM(Protocol):
    def build_interview_map(...) -> InterviewMap: ...
```

M2 只实现 `FakeInterviewMapLLM` 和一个真实 provider adapter。是否内部拆成一次或两次调用是实现细节，不创建多个自主 Agent，不把 SDK 类型泄漏到 service、route 或数据库模型。

成本护栏：

- 默认 `LLM_MODE=fake`，自动化测试与 CI 禁止真实调用；
- 真实模型由配置指定，不在规格中固定易过时的型号；
- 输入/输出 Token 有硬上限，超限在调用前失败；
- 记录 provider、model、prompt/schema version、Token、延迟和估算成本；
- `MONTHLY_LLM_BUDGET_USD` 默认 5 美元，并支持单次验收预算；
- 同一输入快照默认复用成功结果；
- Structured Output 或应用校验失败只允许一次定向修复；
- 并发真实分析初期限制为每用户 1 个、系统 2 个。

预算是防误用护栏，不是财务账单系统。

## 11. 确定性输出校验

持久化前必须通过：

1. `schema_version` 和 JSON Schema；
2. input manifest 的文档 ID、类型、SHA-256 匹配；
3. Evidence、Claim、Risk、Objective、Condition ID 各自唯一；
4. 所有引用存在且方向一致；
5. Evidence 页码、offset、original text 可定位；
6. 每条 Claim 是高价值且有 Evidence；
7. 每条 Risk 满足第五节不变量且只使用五类枚举；
8. 每个 Objective 至少有一个 required Condition；
9. M2 中所有 verification status 均为 `UNVERIFIED`；
10. priority IDs 无重复且引用现有 Risk；
11. 输出总大小不超过配置上限；
12. 地图不含 Storage key、完整材料或供应商原始响应。

第一次不合格可定向修复一次；再次失败记录 `EVIDENCE_VALIDATION_FAILED` 或 `LLM_INVALID_OUTPUT`。

## 12. 数据库设计

### 12.1 修改 documents

- `parsed_at timestamptz null`；
- `parser_version text null`；
- `page_count integer null`。

沿用 `parse_status`、`extracted_text`、`parse_error`。不新建 Page 或 Evidence 关系表；M2 数据量小，页边界文本和 InterviewMap JSONB 足够。

### 12.2 analysis_runs

- `id uuid primary key`；
- `application_id uuid not null references applications(id) on delete cascade`；
- `status text not null`；
- `stage text not null`；
- `input_manifest_json jsonb not null`；
- `interview_map_json jsonb null`；
- `provider text not null`；
- `model text not null`；
- `prompt_version text not null`；
- `schema_version text not null`；
- `error_code text null`；
- `error_message text null`；
- `started_at`、`completed_at`、`created_at`；
- 索引 `(application_id, created_at desc)`；
- 每个 application 最多一个 `PENDING/RUNNING` run 的部分唯一索引。

`interview_map_json` 是单一权威产物，不同时维护可独立漂移的 `profile_json` 和 `risk_json`。

### 12.3 jobs

- 沿用总设计；
- M2 只允许 `job_type=ANALYZE_APPLICATION`；
- `entity_id` 为 analysis run ID，唯一约束 `(job_type, entity_id)`；
- `FOR UPDATE SKIP LOCKED` 原子领取；
- 最多三次尝试，永久输入/Schema 错误不重试；
- 完成 job、analysis 状态和地图写入同一事务。

### 12.4 llm_runs

- 沿用总设计的 operation/entity/provider/model/prompt/status/usage/latency；
- 增加 `estimated_cost_usd numeric(12,6) null`；
- operation 初期只需 `BUILD_INTERVIEW_MAP`，若实现内部两步可增加 `EXTRACT_CLAIMS`；
- 不保存完整输入、完整输出或申请材料。

### 12.5 Project Artifact Vault 扩展

M2 不建 `projects` 或 `artifacts` 表。未来可在新版本将 Evidence 扩展为 `source_type=PROJECT_ARTIFACT` 并增加 artifact-specific location。现有 Risk 只依赖 `evidence_id` 和 `claim_id`，因此不需要改变 Risk/Objective 语义。

## 13. API 变更

### `POST /api/v1/applications/{application_id}/analyses`

- 要求所有权及 CV/PS 齐全；
- 创建分析与 job，返回 `202`；
- 相同 manifest 有活跃任务时返回已有任务；
- 相同 manifest 有成功结果时默认复用；显式重跑创建新版；
- 支持 `Idempotency-Key`。

### `GET /api/v1/analysis-runs/{analysis_run_id}`

- 仅所有者访问，越权统一 `404`；
- 运行中返回 status/stage；
- 完成后返回完整 `interview_map`；
- 不返回 Storage key、完整提取文本或供应商原始响应。

### `GET /api/v1/applications/{application_id}/latest-analysis`

- 只返回与当前 CV/PS manifest 匹配的最新成功分析；
- 没有匹配结果返回 `404 ANALYSIS_NOT_FOUND`。

### `GET /api/v1/documents/{document_id}/extraction`

- 仅所有者访问；
- 只在 `PARSED` 后返回分页预览；
- 不返回 Storage key。

不新增 M3 interview 路由。

## 14. M2 UI

在现有 application detail 页面增量加入，不建设独立 Dashboard。

### 14.1 分析状态

- CV/PS 齐全时显示“分析申请材料”；
- 展示排队、解析、生成地图、失败和重试；
- 每 2 秒轮询，离开页面停止，返回后恢复；
- 文档变化时将旧结果标为过期并隐藏“开始训练”入口。

### 14.2 Candidate Overview

- 一段简要摘要；
- 研究兴趣与重点经历；
- 高价值 claims；
- missing/uncertain information；
- 提供折叠式分页文本预览用于发现解析错误。

### 14.3 Interview Map / Risk Diagnosis

按 `priority_risk_ids` 展示卡片：

- 风险标题、类别、severity；
- 原文 Evidence 及 CV/PS 页码；
- 为什么值得验证；
- Verification Objective 与 Coverage Conditions；
- Suggested Question Types；
- 最大追问次数；
- 当前状态 `Unverified`。

不显示复杂图表、综合分数、录取概率或自动改写入口。

## 15. 稳定错误码

- `ANALYSIS_DOCUMENTS_REQUIRED`
- `ANALYSIS_INPUT_CHANGED`
- `DOCUMENT_DOWNLOAD_FAILED`
- `PDF_PARSE_FAILED`
- `EMPTY_EXTRACTED_TEXT`
- `LLM_NOT_CONFIGURED`
- `LLM_BUDGET_EXCEEDED`
- `LLM_RATE_LIMITED`
- `LLM_UNAVAILABLE`
- `LLM_INVALID_OUTPUT`
- `EVIDENCE_VALIDATION_FAILED`
- `ANALYSIS_FAILED`

错误响应继续使用 M1 envelope 和 `X-Request-ID`；UI 显示安全中文提示。

## 16. 测试与验收

### 16.1 必要测试

- PDF 分页、空文档、扫描件和页数边界；
- InterviewMap JSON Schema 和全部领域不变量；
- Evidence 页码、offset、原文及跨对象引用；
- Coverage Condition 可观察性和枚举；
- Fake provider 成功、非法输出、一次修复和失败；
- job 领取、重试、输入变化和完成事务；
- manifest 匹配、结果复用和文档变化失效；
- A/B 用户隔离，包含分析结果和提取文本；
- 页面刷新恢复和所有 UI 状态；
- 五案例 benchmark 指标计算。

### 16.2 M2 完成标准

1. 当前 CV/PS 可生成合法 `interview-map-v1`；
2. 每条 Risk 满足 Evidence → Claim → Risk → Objective → Condition 链路；
3. Risk 只使用五类 V1 枚举，并包含题型、追问上限和 `UNVERIFIED`；
4. 每项 Evidence 可回到拥有者文档页和原文；
5. 地图可直接实例化第六节 M3 纵向切片；
6. 文档变化不会让旧地图冒充当前；
7. Fake provider 覆盖自动化测试且不产生真实费用；
8. 少量真实验收受预算约束并记录用量；
9. 五案例 Gold 数据、冻结 baseline prompt 和指标脚本齐全；
10. API、Worker、Web 测试和 migration 往返通过。

M2 完成不代表完整训练闭环实现。进入完整 M3 前，应先实现第六节纵向切片并验证地图确实优于通用 Prompt 的泛化输出。

## 17. 过度设计与产品风险

### 必须避免的过度设计

- 为 Evidence 提前建设通用多态 Artifact 数据库；
- 把 Claim 提取、Risk 生成、Objective 生成分别部署成 Agent；
- 为五个 fixture 建设评测平台；
- 把 JSONB 内容过早拆成大量关系表；
- 在 M2 实现问题生成、会话状态或 Evaluation；
- 为成本估算实现复杂财务账本；
- 在没有差异化结果前建设完整 Dashboard。

### 主要产品风险

- **Wrapper 风险**：输出仍可能只是结构化的 ChatGPT 总结。控制方式是 Gold Risk、Evidence grounding 和 Objective verifiability 门槛。
- **伪精确风险**：模型把“材料没写”当成“候选人不会”。所有 Risk 必须写成待验证假设。
- **Claim 泛滥**：抽取所有事实会稀释训练价值。只保留七类高价值 Claim。
- **Coverage Condition 不可判定**：模糊条件会让 M3 状态失真。只允许可观察条件。
- **错误 Gold 标注**：五案例太小，不能证明普遍优越，只用于早期方向判断。
- **UI 抢跑**：漂亮报告会掩盖地图不可执行。纵向切片优先于展示扩展。
- **隐私删除不一致**：删除原材料后若保留原文 Evidence，可能违反用户预期；实施前必须冻结清理策略。

## 18. Scope Freeze

### M2 实现

- CV/PS 文本解析；
- Candidate Profile；
- Evidence；
- 高价值 Candidate Claim；
- 五类 Interview Risk；
- Verification Objective；
- Coverage Conditions；
- versioned Interview Map；
- durable analysis/job persistence；
- Candidate Overview / Risk 极简页面；
- Fake LLM；
- 少量真实 LLM 验收与预算上限；
- 五案例 regression benchmark。

### M2 不实现

- 真正多轮面试；
- Question generation；
- Answer Evaluation；
- Risk 状态动态更新；
- 语音、视频；
- RAG、Vector DB；
- GitHub、源码或 Project Artifact 分析；
- 学校官网自动抓取；
- CV/PS 修改；
- 录取概率；
- 大量新基础设施；
- Multi-Agent 框架。

## 19. 待确认决策

确认后再制定实施计划：

1. 接受 `InterviewMap` 作为 M2 单一权威产物，Candidate Profile 降为辅助视图；
2. 接受 Risk V1 严格限制为五类；
3. 接受跨里程碑 Verification Status 四值枚举，并由 M3 确定性更新；
4. 接受五案例 benchmark 只作为方向门禁，不宣称全面优于 ChatGPT；
5. 确认删除/替换材料后的派生数据物理删除策略；
6. 接受真实模型由配置决定，默认月度预算上限 5 美元。

确认前不开始 M2 代码，也不输出逐任务实施计划。
