# Documentation index | 文档索引

This index separates current product documentation from dated plans and
historical evidence. The product vision is to connect Chinese internet memes
with global social conversations; current verified capabilities and the
remaining localization and platform-integration work are stated in the W13
delivery report.

本索引用于区分当前产品文档、阶段计划和历史证据。产品愿景是连接中文互联网 meme 与全球社交表达；当前已验证能力及仍待实现的文化本地化和平台集成，请先阅读 W13 交付报告。

## Teacher and reviewer reading path | 教师与评审阅读顺序

1. [Project overview / 项目概览](../README.md) — product vision, implemented scope, workflow, team roles and evidence limits.
2. [W13 product delivery / W13 产品交付](../submissions/week13/README.md) — positioning, demo steps, real-media acceptance evidence and outstanding confirmations.
3. [Technical brief / 技术总结](../submissions/week13/final-technical-brief.md) — engineering choices, verification facts and limitations.
4. [Architecture / 系统架构](architecture.md) — current product summary followed by clearly marked W07 and W04 records.
5. [Architecture decision records / 架构决策记录](adrs/README.md) — concise rationale and links to implementation details.

## Run and inspect the product | 运行与查看产品

| Document | Language and purpose |
|---|---|
| [Product deployment / 产品部署](product-deployment.md) | Chinese and English instructions for installation, configuration, Compose deployment, and upgrades. |
| [Backend guide / 后端指南](backend-guide.md) | English technical guide with a Chinese status summary; API, worker, persistence and verification. |
| [Database and vector search / 数据库与向量检索](database-and-vector-search.md) | Chinese and English technical guidance for schemas, lifecycle, indexing, capacity assumptions, and evolution criteria. |
| [HKUST and DeepSeek execution / 供应商运行说明](hkust-deepseek-execution.md) | Chinese configuration runbook with an English scope/security/status overview; secrets must remain local. |
| [Local demo / 本地演示](local-demo.md) | Bilingual scope note plus the historical W07 small-corpus local profile; use product deployment for the current full product. |
| [Container release / 容器发布](container-release.md) | Chinese release runbook with an English overview; immutable image verification, upgrade, and rollback. |

## Evidence and evaluation | 证据与评估

- [Formal web and offline-reuse receipt / 正式网页与离线复用回执](evidence/gif-acquisition/hkgai-web-offline-20261128.json)
- [Chinese meme retrieval benchmark / 中文 meme 检索评测](retrieval-benchmark-at-scale.md) — machine evaluation, corpus boundaries, weak categories, and pending human review.
- [W13 fixed-corpus evaluation / W13 固定语料评估](../submissions/week13/local-corpus-evaluation.json)
- [Evaluation protocol / 评估方案](yuanjian-benchmark-guide.md)
- [AI-use statement / AI 使用说明](../submissions/week13/ai-use-statement.md)

Evidence records describe specific runs and samples. The 2,960-run meme
benchmark is a machine evaluation over a fixed corpus and generated variants;
it is not a real-user study. Neither it, a single successful workflow, nor the
12-item fixed-corpus comparison should be presented as a general retrieval-
accuracy estimate.

证据文件只说明特定运行和样本。2,960 次 meme 评测是固定语料上的机器评测，截图变化由程序生成，不是实际用户研究。单次成功闭环、该机器评测或 12 项固定语料对照，均不应表述为总体检索准确率。

## Historical plans and experiments | 历史计划与实验

- [Final-project plan / 后半程项目计划](final-project-plan.md) — Chinese dated scope and ownership plan with a bilingual status note; not a current completion report.
- [Final closeout plan / 期末收尾计划](final-closeout-plan.md) — combines dated branch snapshots, completed acceptance evidence and outstanding tasks; read its status note first.
- [Operations notes / 运维说明](operations.md) — W07-era local-profile notes; the scope banner links to current deployment instructions.
- [W07 submission](../submissions/week07/README.md) and [W04 submission](../submissions/week04/README.md) — earlier course milestones.
- Provider, import, browser, and retrieval experiments are retained under this folder with their dates and evidence references. Their results apply only to the configurations and runs stated in each record.

## Record status | 记录状态

Product ADRs are retrospective summaries of implementation and remain subject
to team review. Dated test reports and evidence files are historical records;
they are not silently rewritten when later code or results change.

产品 ADR 是对当前实现的回顾性总结，仍待团队评审。带日期的测试报告和证据文件属于历史记录；后续代码或结果变化时，不会将其改写成新的事实。
