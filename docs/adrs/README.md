# Architecture decision records | 架构决策记录

These records describe decisions reflected in the current repository. ADR 0001
documents the course starter; the later records are retrospective summaries of
the product implementation, not evidence of a separate formal approval or a
benchmark of every alternative.

以下记录概述仓库中已实现的架构选择。ADR 0001 记录课程 starter；其余 ADR 是对产品实现的回顾性总结，不代表团队曾正式批准所有决策，也不代表对所有替代方案做过基准测试。

Each product record explains the problem, current decision, alternatives,
consequences, and conditions that would justify reconsidering it. "Pending team
review" means the record describes the implementation but has not been
independently approved as a team decision. The linked implementation and
operating guides are the source of truth for current configuration and results.

| ADR | Decision / 决策 |
| --- | --- |
| [0001](0001-baseline-stack.md) | Course starter technology stack / 课程 starter 技术栈 |
| [0002](0002-relational-persistence.md) | PostgreSQL plus separate persistent media / PostgreSQL 与独立持久媒体存储 |
| [0003](0003-background-jobs.md) | Database-backed jobs and a dedicated worker / 数据库任务队列与独立 worker |
| [0004](0004-ai-and-search-integration.md) | Local vision, web search and user review / 本地视觉检索、联网搜索与人工审核 |
| [0005](0005-compose-deployment.md) | Docker Compose product deployment / Docker Compose 产品部署 |
| [0006](0006-vector-indexing.md) | Exact frame-vector search with NPZ fallback / 精确帧向量检索与 NPZ 回退 |

Product ADRs are written in English. The Chinese decision summaries above are
navigation aids; use each linked record and the implementation guides for
technical details and current behavior.

产品 ADR 正文为英文。上表中文用于快速导航；具体技术细节和当前行为以各 ADR 正文及实现指南为准。
