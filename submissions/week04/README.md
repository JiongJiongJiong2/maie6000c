# W04 Team Architecture Proposal and Project Plan

| Field | Value |
|---|---|
| Course | MAIE 6000C |
| Team name | Memeory |
| Members | Jiongle He (leader), Haoxuan Jiang, YuanJian Li, Zirui Huang |
| Selected project title | MemeRetrieve: Screenshot-to-Animated-Meme Recovery |
| Assignment type | Team |
| Focus | Architecture and scope planning |
| Required tag | `w04-proposal` |
| Primary artifact | `submissions/week04/README.md` |
| Current state | W04 proposal approved for repository publication by the team lead; implementation checks pending |

## Team and responsibilities

**Team name: Memeory** - a blend of *meme* and *memory*, reflecting the goal of finding and remembering animated memes.

| Member | Student ID | Role | Responsibilities |
|---|---|---|---|
| Jiongle He | 21321732 | Team leader; direction and scope | Set product direction and priorities; control scope; coordinate milestones and proposal decisions; lead final acceptance and submission coordination |
| Haoxuan Jiang | 21313230 | Backend, data, and deployment | Implement FastAPI contracts, PostgreSQL schema/migrations, durable jobs and idempotency, shared storage, Docker deployment, and backend verification |
| YuanJian Li | 21324552 | Retrieval, AI, and evaluation | Prepare the permitted GIF corpus/provenance, frame sampling and pretrained inference, ranking/no-match behavior, model/corpus versioning, and retrieval evaluation |
| Zirui Huang | | Client and integration | Implement image import/cropping, local metadata/media storage, submission/polling, preview/review/download, and lead device checks and end-to-end integration |

Owners coordinate at the API/result contracts: Haoxuan Jiang supplies persistent services, YuanJian Li supplies worker retrieval, and Zirui Huang connects the client workflow. Jiongle He focuses on direction, scope, milestone decisions, and acceptance rather than being the primary implementation owner.

## Proposal summary

MemeRetrieve helps an iPhone user recover an existing animated meme from a screenshot, review candidates, and save a playable GIF locally. The initial scope is one user, one selected crop, and a curated GIF corpus. The broader motivation comes from Douyin screenshots, but the initial baseline does not claim general internet coverage.

The planned corpus starts with 50-100 GIFs the team owns or has permission to use. Actual collection and resource checks remain pending. A pretrained image encoder ranks sampled GIF frames against a submitted crop; optional OCR can later assist captioned memes. The user decides whether a candidate is correct. Out-of-corpus inputs may yield no match.

## Workflow and architecture

The phone stores collected screenshots offline. FastAPI validates an uploaded crop and commits a request plus pending job before returning `202`. A separate worker performs live feature extraction, corpus retrieval, animation validation, and persistent result storage. The phone queries status, records acceptance/rejection, and downloads the selected file. Search completion, user acceptance, and phone-save success are separate states.

The backend proposal is FastAPI, PostgreSQL, SQLAlchemy, Alembic, and a database-backed worker on one personal computer. Inference/ranking are worker modules behind explicit interfaces; starter adaptation must retain reproducible deployment and verification. The inference interface can also be exposed over HTTP if a later course requirement specifies a separate AI service. SwiftUI with SQLite/local files is the proposed phone client, conditional on native development access.

Five persistent entities are ReferenceAsset, SearchRequest, SearchJob, Candidate, and ReviewDecision. Phone records are CollectionItem and SavedMeme. Reference GIFs/frames/features remain in a persistent computer-side corpus. Input crops and candidate transport copies are a separate temporary class with an initial seven-day terminal-job retention policy. Personal screenshots and selected GIFs stay on the phone.

## Technical figures

All labels and captions are in English. Figures are embedded in [the architecture document](../../docs/architecture.md), with SVG previews and editable Mermaid sources in [the figure index](../../docs/figures/README.md).

| Figure | Review purpose |
|---|---|
| 1. [System architecture](../../docs/figures/system-architecture.svg) | Phone/computer boundaries, API/worker, DB, persistent corpus versus temporary media |
| 2. [Async sequence](../../docs/figures/search-sequence.svg) | Committed acceptance before background work, polling, review, download, errors |
| 3. [Data model](../../docs/figures/data-model.svg) | Five entities, relations, nullable review selection |
| 4. [Job states](../../docs/figures/job-states.svg) | Pending/running/completed/failed; explicit new attempts |
| 5. [Retrieval pipeline](../../docs/figures/retrieval-pipeline.svg) | Corpus preparation, live pretrained inference, ranking, validation and review |

## AI-enabled function and retrieval boundaries

The product's AI function is live pretrained image-feature extraction for a selected crop and sampled reference frames. GIF-level ranking compares these vectors without model training or a vector database. Model, sampling, ranking, and corpus versions are recorded. Scores are ranking signals, not probabilities of a correct match. OCR/tag ranking is a follow-up improvement to compare with visual-only retrieval.

External lookup is an extension, conditional on verified access, actual animation retrieval, allowed integration behavior, and acceptable cost. It is not the committed first baseline. If visual inference cannot run within the available resources, the team must select and test a smaller encoder or a narrower OCR-based scope before W05; manual keywords or canned outputs cannot substitute for the course AI slice.

## Semester milestones

| Stage | Planned deliverable |
|---|---|
| W04 | Team-reviewed proposal, five figures, persistence/API/worker design, risks, repository checkpoint |
| Before W05 freeze | Document permitted corpus, run actual pretrained inference/ranking, decide native client feasibility |
| W05 | Durable request/job API, migration, query and duplicate-submit behavior |
| W07 | Live input -> persistent job -> real AI/retrieval -> stored result -> status/log evidence; review/save where client ready |
| W09 | Reproducible Docker deployment with shared volumes and model/corpus preparation |
| W11 | Measured reliability, observability, or performance improvement |
| W12 | Held-out checks, final workflow validation, demo preparation |
| W13 | Final repository checkpoint/submission, reconciled with the final assignment |

Jiongle He coordinates direction and scope; Haoxuan Jiang owns backend/data/deployment; YuanJian Li owns retrieval/AI/evaluation; Zirui Huang owns client/integration. Each milestone has acceptance evidence and named owners in architecture §12.

## Risks and scope discipline

Main risks are corpus coverage/permission, image-model ranking and resources, native phone access, ambiguous frame matches, interrupted worker execution, and expired task media. The corpus is a limited baseline, not evidence of broad real-world recovery. Manual import/simple client can preserve a reduced backend course slice when native collection is blocked.

Cut WeChat/mini-program integration first, automatic crop/model training second, then batching/multiple platforms/external sources. Preserve durable jobs, live AI inference, real GIF output, human review, and inspectable outcomes. Each risk has a gate, owner role, and fallback in architecture §§9 and 13.

## Evaluation and current evidence

Freeze corpus/model versions and split development queries from held-out queries. Test different frames, backgrounds, crop/scale changes, and out-of-corpus inputs. Report Top-3 confirmed recovery on in-corpus inputs, out-of-corpus false acceptance/no-match behavior, and phone-save success separately. Indexed-GIF tests do not demonstrate discovery of unseen animations.

A separate 20-30-real-screenshot feasibility study assesses the wider product goal and manual-search baseline. Record unresolved targets, failures, latency, actions, and resource use. No implementation tests, device trials, collected corpus, or measured recovery results are supplied at W04.

## Rubric map

| Category | Points | Evidence |
|---|---|---|
| Problem and workflow | 20 | Architecture §§1-3 |
| Architecture feasibility | 20 | §§4, 9; Figures 1-2 |
| Data and persistence | 15 | §§5-6; Figures 3-4 |
| API and async workflow | 15 | §§6-8; Figures 2, 4-5 |
| Scope and milestones | 15 | §§2, 12 |
| Risks and fallbacks | 10 | §§9, 13 |
| Written communication | 5 | Project README, this review entry, linked architecture/figures |

## AI Use Statement

**Tools and use:** OpenAI ChatGPT/Codex in ChatGPT Work assisted with proposal drafting and revision, requirements review, and preparation of five English technical diagrams as Mermaid source and rendered SVG figures. The diagrams were rendered from code; no generative image model was used.

**Revision record:** The AI-assisted revision selected a bounded corpus as the proposed first retrieval baseline, separated reference storage from temporary task files, added corpus provenance/versioning and retry-key persistence, and clarified expired-media resubmission. Assistant checks cover document links, figure rendering, and consistency of the stated entities/workflow. These checks are not team-run implementation experiments.

**Team lead review and revision record:** Jiongle He supplied and confirmed the four-member roster, directed the division of responsibilities, requested English technical diagrams and the bounded retrieval proposal, and authorized publication of this checkpoint. The proposal was narrowed to a curated-corpus first baseline; general internet recovery is not claimed. Diagram rendering and document-link checks were performed by the assistant. Independent review by the other members and model/corpus/device implementation checks are not claimed; retrieval performance remains unverified.

## Checkpoint and Canvas record

The repository checkpoint consists of the required documents and `docs/figures/`, identified by the pushed `w04-proposal` tag. Canvas must separately receive the repository URL, required tag, tagged commit SHA, primary artifact path, team name, project title, and optional note. Repository publication does not itself submit the Canvas assignment.
