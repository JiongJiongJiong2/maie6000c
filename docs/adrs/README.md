# Architecture decision records

These records describe decisions reflected in the current repository. ADR 0001
documents the course starter; the later records are retrospective summaries of
the product implementation, not evidence of a separate formal approval or a
benchmark of every alternative.

Each product record explains the problem, current decision, alternatives,
consequences, and conditions that would justify reconsidering it. "Pending team
review" means the record describes the implementation but has not been
independently approved as a team decision. The linked implementation and
operating guides are the source of truth for current configuration and results.

| ADR | Decision |
| --- | --- |
| [0001](0001-baseline-stack.md) | Course starter stack |
| [0002](0002-relational-persistence.md) | PostgreSQL and shared media storage |
| [0003](0003-background-jobs.md) | Database-backed jobs and separate worker |
| [0004](0004-ai-and-search-integration.md) | Vision, web search and local visual ranking |
| [0005](0005-compose-deployment.md) | Docker Compose deployment |
| [0006](0006-vector-indexing.md) | Exact frame-vector search with NPZ fallback |
