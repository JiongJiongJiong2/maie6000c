# MemeRetrieve

**Recover an existing animated meme from a screenshot, review candidates, and save the selected GIF locally.**

MemeRetrieve is a proposed MAIE 6000C semester project motivated by an iPhone user who sees an animated meme in Douyin comments but cannot obtain its media file. It separates quick screenshot collection from later search and review. The first retrieval baseline searches a curated GIF corpus; recovery of arbitrary internet screenshots is a later feasibility question.

## Project status

This checkpoint is an architecture proposal. Application behavior, model/resource feasibility, corpus assets, device integration, and retrieval performance have not been verified through implementation tests.

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

## Team and responsibilities

**Team name: Memeory** - a blend of *meme* and *memory*, reflecting the goal of finding and remembering animated memes.

| Member | Student ID | Role | Responsibilities |
|---|---|---|---|
| Jiongle He | 21321732 | Team leader; direction and scope | Set product direction and priorities; control scope; coordinate milestones and proposal decisions; lead final acceptance and submission coordination |
| Haoxuan Jiang | 21313230 | Backend, data, and deployment | Implement FastAPI contracts, PostgreSQL schema/migrations, durable jobs and idempotency, shared storage, Docker deployment, and backend verification |
| YuanJian Li | 21324552 | Retrieval, AI, and evaluation | Prepare the permitted GIF corpus/provenance, frame sampling and pretrained inference, ranking/no-match behavior, model/corpus versioning, and retrieval evaluation |
| Zirui Huang | | Client and integration | Implement image import/cropping, local metadata/media storage, submission/polling, preview/review/download, and lead device checks and end-to-end integration |

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

This package supplies no application startup commands because MemeRetrieve is not implemented. When merged into the actual course repository, preserve its existing starter startup/test instructions and distinguish them from proposed product behavior.

## Evidence and submission

The assignment is the source for W04 requirements. Technical documentation references and unresolved decisions are listed in the architecture. The corpus is planned, not yet collected; no accuracy or provider availability is claimed. Team identity and ownership are recorded below the project summary. The Week 4 AI Use Statement records the team lead's directions and publication approval, distinguishes assistant checks, and identifies unverified implementation work.

The team lead has authorized this proposal checkpoint for repository publication. The required repository tag is `w04-proposal`; Canvas submission uses its commit SHA and remains a separate step. The Chinese preparation guide and Canvas template in the local package are internal submission aids.

## Course starter and development

The repository still contains the course's case/job/triage starter implementation, including its separate internal AI service. The proposed MemeRetrieve schema, routes, client, and local pretrained retrieval have not been implemented at this checkpoint. Existing application code, migrations, and verification remain the starter baseline.

The original [starter guide](docs/starter-guide.md) and [starter architecture](docs/starter-architecture.md) preserve the existing operating instructions and baseline flow. They describe the current code; [the project architecture](docs/architecture.md) describes the proposed semester change.

### Run the starter

```bash
cp .env.example .env
docker compose up --build
```

API documentation: `http://localhost:8000/docs`. Internal AI service documentation: `http://localhost:8100/docs`.

### Starter verification and migrations

```bash
pytest -q
SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q
docker compose run --rm api alembic upgrade head
```

These commands refer to the existing starter, not an implemented MemeRetrieve application. See the starter guide for observability, seed data, and other development commands.
