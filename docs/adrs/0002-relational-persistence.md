# ADR 0002: Use PostgreSQL for product data

## Status

Implemented; retrospective record, pending team review.

## Context

Requests, job attempts, reviews, saved assets and private-library imports must
survive restarts. Relationships and idempotency keys must remain consistent
across the API and worker. Media files are too large to treat as ordinary
relational records. The product also needs to distinguish temporary candidate
files from durable user collections, without reporting an accepted review as
proof that a file has been saved or indexed.

## Decision

Use PostgreSQL 16 for product relational state, SQLAlchemy for models and
Alembic for schema migrations. Store original media on persistent shared
storage and keep paths and integrity metadata in the database. SQLite remains
available for development and tests; it is not the product Compose database.

Important boundaries:

- A request can have multiple attempts; a partial unique index limits it to
  one pending or running job. Client keys support replay and conflict detection.
- Reviews, candidate saves and saved assets are separate records. A saved
  original and its indexing status have different lifecycles.
- Account workspaces use separate PostgreSQL schemas and media roots. Shared
  reference media and model files are managed separately from private media.
- A file write and a database transaction are not one atomic operation. The
  application uses checksums, publication locks and cleanup for recovery;
  operators must still preserve both stores during backup and restore.

## Alternatives considered

- **SQLite only:** simple to start, but the product also needs PostgreSQL
  transaction and row-locking behavior for its separate worker.
- **Another relational database:** possible, but adopting it would require
  reworking and testing the current PostgreSQL-specific locking, migrations
  and optional pgvector integration.
- **Files only:** avoids a database service, but makes relationships,
  uniqueness and concurrent state changes harder to enforce.

These are trade-offs recorded retrospectively, not a claim that the team
benchmarked every alternative.

## Consequences

Database constraints and transactions protect persistent state, while original
media remains separately accessible. PostgreSQL and the media volume both
require coordinated backups and operational maintenance; a database backup
alone does not preserve the GIF files. Product accounts use separate
workspaces, but current isolation depends on application routing and does not
by itself provide database-role isolation.

## Reconsider when

- The deployment requires database-enforced tenant isolation: design and test
  separate roles, permissions and workspace migrations rather than assuming
  schema routing alone is sufficient.
- Storage becomes distributed or independently managed: define an explicit
  publication, deletion and recovery protocol for database/file mismatches.
- The database backend changes: revalidate locking, partial indexes, foreign
  keys, migrations and idempotency rather than assuming SQLite tests prove
  PostgreSQL behavior.

## References

- [Database relationships and workspace isolation](../database-and-vector-search.md)
- [Deployment and upgrade instructions](../product-deployment.md)
- [Search models and constraints](../../services/common/search_models.py)
- [PostgreSQL integration tests](../../tests/integration/test_search_postgres.py)
