# ADR 0005: Deploy the product with Docker Compose

## Status

Implemented; retrospective record, pending team review.

## Context

The product needs an API, worker, PostgreSQL, model files and a public media
fetcher with reproducible configuration and persistent data. It must also be
possible to start and inspect the stack on a development machine.

## Decision

Use Docker Compose for the product deployment, with separate API, worker,
database and media-fetch services and persistent volumes for database and
media data. The product guide combines the base Compose file with local-model
and pgvector overlays. A release overlay can use verified, versioned container
images. The starter AI service is optional and is not the product retrieval
worker.

The documented product profile uses:

| Component | Responsibility |
| --- | --- |
| API | Accept requests, serve the web client and expose persistent state |
| Worker | Process jobs, run retrieval and publish indexing outcomes |
| PostgreSQL | Persist relational state and, with the overlay, frame vectors |
| `media-fetch` | Fetch public media on a separate egress network |
| Persistent storage | Retain database data, user media and model cache |

The reference library is a separate host mount. Image preparation and database
migrations are deployment steps, not evidence that a container alone contains
the corpus or model weights.

## Alternatives considered

- **Native processes:** already supported by the local launcher and useful on
  a development machine, but operators must manage more host dependencies and
  process configuration themselves.
- **A container orchestration platform:** could support a larger deployment,
  but introduces infrastructure and operational complexity beyond the
  repository's documented local product stack.

## Consequences

Services, volumes and health checks can be configured together, and the media
fetcher has a separate network boundary. Operators still need to prepare model
weights and reference data, configure private credentials, run migrations,
and back up both database and media. Compose alone does not make the system a
secure public service or provide high availability.

## Operational implications and reconsideration

- Preserve the Compose project name and existing volumes during upgrades.
  Back up database and media together before migration; do not treat
  `docker compose down -v` as routine cleanup.
- The release procedure pins images by digest and retains the preceding
  version for rollback. A successful image build alone does not prove that
  existing data has been migrated or that provider credentials work.
- If availability, scaling or independent service deployment requirements
  grow, evaluate orchestration and managed storage with explicit migration,
  networking, credential and recovery plans.

## References

- [Product deployment](../product-deployment.md)
- [Versioned container release](../container-release.md)
- [Base Compose configuration](../../compose.yaml)
- [pgvector overlay](../../compose.pgvector.yaml)
