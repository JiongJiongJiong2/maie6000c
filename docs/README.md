# MemeRetrieve documentation

English · [简体中文](README.zh-CN.md) · [Repository home](../README.md)

| Start here | What you will find |
| --- | --- |
| [Product](product/README.md) | Use cases, capabilities, known limits and the proposed business pilot |
| [User and operator guides](guides/README.md) | Accounts, screenshot searches, collections, Docker deployment, beta rehearsal, upgrades and rollback |
| [Technical documentation](technical/README.md) | Architecture, API, workers, pgvector, NPZ fallback, migrations and tests |

## Current delivery and verification

[Week 13 delivery](../submissions/week13/README.en.md) · [Technical brief](../submissions/week13/final-technical-brief.en.md) · [AI use statement](../submissions/week13/ai-use-statement.en.md)

| Question | Run record |
| --- | --- |
| Did a real browser recover the original online and find it offline after a restart? | [Browser release check](../submissions/week13/browser-release-verification.json) |
| Did an old collection migrate and return the same asset through pgvector and NPZ? | [Vector database checks](../submissions/week13/pgvector-verification.json) |
| How did first-frame and multi-frame indexes compare on the 12 reference GIFs? | [Per-GIF results](../submissions/week13/local-corpus-evaluation.json) |
| Did invitation registration, offline search and original download work in the local beta? | [Before and after restart](../submissions/week13/public-beta-rehearsal.json) |

## Specialist references and original records

These records are grouped by subject. Each link identifies the language of its source or its data format. Dated results describe the version tested at the time. Use the guides above for current setup instructions.

<details>
<summary>Application and storage</summary>

| Source | Language / format |
| --- | --- |
| [Architecture and original design](architecture.md) | EN |
| [Backend contracts and media lifecycle](backend-guide.md) | EN |
| [Backend development log](backend-development-log.md) | Chinese |
| [Service operations](operations.md) | EN |
| [Native launcher and local demo](local-demo.md) | EN |
| [Architecture figures](figures/README.md) | EN |
| [W07 web client integration](../web/README.md) | EN |
| [Web design direction](../web/DESIGN.md) | EN |
| [Browser compatibility checks](yuanjian-web-compatibility.md) | Chinese |
| [Private-library features](private-meme-library-p0-p1.md) | Chinese |
| [Private-library acceptance record](private-meme-library-acceptance.md) | Chinese |
| [Large GIF restore test](private-library-large-restore.md) | Chinese |

</details>

<details>
<summary>Search, sources and providers</summary>

| Source | Language / format |
| --- | --- |
| [Search worker handoff](web-search-agent.md) | Chinese |
| [Image-first search profile](meme50.md) | Chinese |
| [HKUST, HKGAI and DeepSeek integration](hkust-deepseek-execution.md) | Chinese |
| [HKUST setup record](hkust-meme50-setup.md) | Chinese |
| [Provider authorization record](meme50-authorization.md) | Chinese |
| [GIF source support](gif-source-support.md) | EN |
| [Original acquisition and handoff](gif-acquisition-verification.md) | EN |
| [Standalone search agent experiment](meme-agent-v1.md) | Chinese |
| [Pilot workspace](../experiments/meme_search/README.md) | Chinese |
| [Pilot protocol](../experiments/meme_search/protocol.md) | EN |
| [Pilot implementation contract](../experiments/meme_search/mvp_contract.md) | EN |
| [Pilot agent procedure](../experiments/meme_search/meme-search-skill.md) | EN |

</details>

<details>
<summary>Retrieval evaluation and run history</summary>

| Source | Language / format |
| --- | --- |
| [Benchmark and split protocol](yuanjian-benchmark-guide.md) | Chinese |
| [Three user GIFs and nine candidates](gif-user-sample-test.md) | EN |
| [Search verification protocol and results](meme50-verification.md) | Chinese |
| [Human review instructions](meme50-human-review.md) | Chinese |
| [November 12 acceptance run](meme50-acceptance-20261112.md) | Chinese |
| [Live service run history](meme50-live-20261112.md) | Chinese |
| [Frozen v8 results](meme50-v8-results.md) | Chinese |
| [Deduplication fix and checks](meme50-dedup-fix-20261113.md) | Chinese |
| [Earlier milestone audit](meme50-goal-audit.md) | Chinese |
| [Retrieval handoff](yuanjian-handoff-20261115.md) | Chinese |
| [Branch artifacts audit](yuanjian-branch-material-audit.md) | Chinese |
| [Machine-readable runs and failure records](evidence/) | JSON |

</details>

<details>
<summary>Sharing and import experiments</summary>

| Source | Language / format |
| --- | --- |
| [WhatsApp web import experiment](whatsapp-web-import-experiment.md) | Chinese |
| [Implementation and reproduction](../experiments/whatsapp_web_import/README.md) | Chinese |
| [WeChat sharing investigation](wechat-gif-sharing-investigation.md) | Chinese |
| [QQ import feasibility](qq-import-feasibility.md) | Chinese |

</details>

<details>
<summary>Course materials and repository maintenance</summary>

| Source | Language / format |
| --- | --- |
| [W03 readiness lab](../submissions/week03/README.md) | EN |
| [W04 team proposal](../submissions/week04/README.md) | EN |
| [W07 midterm demo](../submissions/week07/README.md) | EN |
| [W07 integration plan](week07-plan.md) | Chinese |
| [Team responsibilities and evaluation design](final-project-plan.md) | Chinese |
| [Final delivery plan](final-closeout-plan.md) | Chinese |
| [Original course starter guide](starter-guide.md) | EN |
| [Original course starter architecture](starter-architecture.md) | EN |
| [Baseline stack decision](adrs/0001-baseline-stack.md) | EN |
| [Course submission and AI disclosure templates](../templates/) | EN |
| [Repository administration tooling](../tooling/github/README.md) | EN |
| [CI workflows and issue templates](../.github/) | EN |

</details>
