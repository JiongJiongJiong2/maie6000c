# MemeRetrieve

**Recover an existing animated meme from a screenshot, review candidates, and save the selected GIF locally.**

MemeRetrieve is a proposed MAIE 6000C semester project motivated by an iPhone user who sees an animated meme in Douyin comments but cannot obtain its media file. It separates quick screenshot collection from later search and review. The first retrieval baseline searches a curated GIF corpus; recovery of arbitrary internet screenshots is a later feasibility question.

## Project status

The local W07 demo now connects the web client, PostgreSQL, an independent worker, and real CLIP image retrieval over 12 attributed animated reaction GIFs. Upload, candidate review, and original GIF download are available at `http://127.0.0.1:8000/web/`. Follow the [local demo guide](docs/local-demo.md) to prepare and run it. The collection is deliberately small; arbitrary internet meme recovery and physical iPhone acceptance remain unverified. The W04 proposal is preserved below.

| Item | Proposal |
|---|---|
| Course | MAIE 6000C - Engineering AI Products: From Prototype to Production |
| Working title | MemeRetrieve: Screenshot-to-Animated-Meme Recovery |
| Team name | Memeory |
| Members | Jiongle He (leader), Haoxuan Jiang, YuanJian Li, Zirui Huang |
| Initial user | One iPhone user |
| Input | One manually selected screenshot crop |
| Retrieval baseline | Planned 50-100-GIF curated corpus with documented permission |
| Backend | Personal computer: FastAPI, PostgreSQL, database-backed worker |
| AI function | Live pretrained image-feature inference for frame-to-GIF ranking |
| Storage | Personal screenshots/saved GIFs on phone; reference corpus on computer; temporary task media separate |
| Current milestone | W04 Team Architecture Proposal and Project Plan |
| Required tag | `w04-proposal` |

For the Week 7 implementation scope, task owners, API conventions, and integration schedule, see the [Week 7 team plan](docs/week07-plan.md).

Development follows `feature/fix/docs branch → dev → main`. Create work branches from the latest `dev` and target pull requests to `dev`. After integration and acceptance, merge `dev` into `main`; create milestone tags from the accepted `main` commit.

## Team and responsibilities

**Team name: Memeory** - a blend of *meme* and *memory*, reflecting the goal of finding and remembering animated memes.

| Member | Student ID | Role | Responsibilities |
|---|---|---|---|
| Jiongle He | 21321732 | Team leader; direction and scope | Set product direction and priorities; control scope; coordinate milestones and proposal decisions; lead final acceptance and submission coordination |
| Haoxuan Jiang | 21313230 | Backend, data, and deployment | Implement FastAPI contracts, PostgreSQL schema/migrations, durable jobs and idempotency, shared storage, Docker deployment, and backend verification |
| YuanJian Li | 21324552 | Retrieval, AI, and evaluation | Prepare the permitted GIF corpus/provenance, frame sampling and pretrained inference, ranking/no-match behavior, model/corpus versioning, and retrieval evaluation |
| Zirui Huang | 21313436 | Client and integration | Implement image import/cropping, local metadata/media storage, submission/polling, preview/review/download, and lead device checks and end-to-end integration |

Owners coordinate at the API/result contracts: Haoxuan Jiang supplies persistent services, YuanJian Li supplies worker retrieval, and Zirui Huang connects the client workflow. Jiongle He focuses on direction, scope, milestone decisions, and acceptance rather than being the primary implementation owner.

## Core workflow

Collect locally -> select/crop -> submit -> persist request/job -> worker extracts visual features and ranks corpus GIFs -> validate/store candidates -> user reviews -> download and verify local playback.

Collection continues while the computer is offline. The API acknowledges durable work before retrieval begins. Execution completion, human acceptance, and successful phone saving are separate outcomes. Missing corpus matches may produce no candidates.

## Semester scope

Core scope is one user, one target per request, manual crop, a persisted async task, real pretrained inference, real GIF output, human review, local storage, and explicit failures/retries. The proposed client is SwiftUI with SQLite metadata and local files, conditional on Mac/Xcode and device access. A simpler upload/review client is a reduced course-slice fallback.

OCR-assisted ranking, shortcut/share collection, automatic crop suggestions, batching, a verified external source, and WeChat export follow the core. Multi-user accounts, personal cloud libraries, model training, vector databases, and unrestricted web recovery are excluded.

## Proposal artifacts

| Artifact | Purpose |
|---|---|
| [Week 4 submission](submissions/week04/README.md) | Primary review entry, milestone/risk summary, rubric map, AI Use Statement |
| [Architecture](docs/architecture.md) | Deployment, persistence, states, APIs, async flow, retrieval and evaluation |
| [English technical figures](docs/figures/README.md) | Architecture, sequence, ERD, job states, retrieval pipeline; editable Mermaid plus SVG previews |

The backend has separate API and worker processes. Pretrained inference/ranking are initially worker modules behind a bounded interface; starter adaptation and any course requirement for a separate AI service must be checked before implementation. SQLAlchemy/Alembic define the relational model and migrations.

The W07 backend startup and tests are documented in the
[backend guide](docs/backend-guide.md). For an implementation-oriented
architecture walkthrough and development log of Haoxuan's backend, data, and
deployment work, see the
[backend development log](docs/backend-development-log.md). The starter remains
available using its Compose profile; neither backend scaffolding nor test
fixtures establish a working pretrained retrieval product.

## Evidence and submission

The assignment is the source for W04 requirements. Technical documentation references and unresolved decisions are listed in the architecture. The corpus is planned, not yet collected; no accuracy or provider availability is claimed. Team identity and ownership are recorded below the project summary. The Week 4 AI Use Statement records the team lead's directions and publication approval, distinguishes assistant checks, and identifies unverified implementation work.

The team lead has authorized this proposal checkpoint for repository publication. The required repository tag is `w04-proposal`; Canvas submission uses its commit SHA and remains a separate step. The Chinese preparation guide and Canvas template in the local package are internal submission aids.

## Course starter and development

The repository retains the course's case/job/triage starter implementation, including its separate internal AI service. The MemeRetrieve backend schema and routes are implemented alongside that baseline. The local demo integrates the web client and pretrained retrieval; see the local demo guide above.

The original [starter guide](docs/starter-guide.md) and [starter architecture](docs/starter-architecture.md) preserve the existing operating instructions and baseline flow. They describe the current code; [the project architecture](docs/architecture.md) describes the proposed semester change.

### Run the starter

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD in .env to a private hexadecimal value before starting.
docker compose --profile starter up --build
```

API documentation: `http://localhost:8000/docs`. Internal AI service documentation: `http://localhost:8100/docs`.

### Starter verification and migrations

```bash
pytest -q
SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q
docker compose run --rm api alembic upgrade head
```

The case-flow smoke test requires the `starter` profile. See the [backend guide](docs/backend-guide.md) for search-specific smoke tests and PostgreSQL concurrency/migration verification, and the starter guide for seed data and other baseline commands.

### W07 web client

The web client is served by the API at `http://localhost:8000/web/`. It implements
image upload, status polling, animated candidate previews, review, and download.
See [the web guide](web/README.md) for setup, API integration, verification evidence,
and the API contract. For the complete running stack, use the
[local demo guide](docs/local-demo.md).
