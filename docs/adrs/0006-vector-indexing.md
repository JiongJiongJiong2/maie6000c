# ADR 0006: Use exact frame-vector search with an NPZ fallback

## Status

Implemented; retrospective record, pending team review.

## Context

Matching a screenshot against an animation requires comparing more than its
first frame. Saved GIFs must remain reusable after restart and be associated
with the correct account, original file and index version.

## Decision

Encode representative GIF frames with the pinned CLIP model, retain
versioned NPZ indexes, and aggregate frame similarity to an asset-level
result. The product pgvector deployment supports exact vector search;
validated NPZ indexes remain available as a fallback when vector data or the
extension cannot be used. Save the original GIF separately and mark indexing
ready only after successful validation and publication.

For the documented implementation, CLIP produces normalized 512-dimensional
frame vectors. A GIF is sampled at up to eight representative frames; local
search compares the query with those frames and ranks an asset by its best
frame. Saved index versions bind the asset, original checksum, model and
sampling information. The worker verifies the original and writes a validated
versioned NPZ before marking it ready.

## Alternatives considered

- **NPZ-only exact search:** fewer database extensions and still supported,
  but reads and scores local index files as the collection grows.
- **Approximate indexes such as HNSW:** may help at larger scale, but require
  measured latency and recall evaluation before replacing exact behavior.
- **A separate vector database:** would add another service and migration
  boundary; the current product already operates PostgreSQL and retains NPZ
  compatibility.

## Consequences

Search results can be reproduced against a recorded model and index version,
and the original GIF is retained independently of its vectors. The product
must provision pgvector and maintain both index representations when using
that backend. Exact search and integrity checks have increasing cost as the
library grows; similarity is a ranking signal, not a calibrated probability or
proof that a result is correct.

## Operational implications and reconsideration

- The pgvector overlay requires provisioning and, for an existing library,
  backfilling the relevant workspaces. Keep the original media and NPZ indexes
  available during upgrade and rollback.
- The application checks versions and integrity before using saved vectors;
  incomplete or incompatible vector data must not be treated as a successful
  index update.
- Before introducing an approximate index, measure latency, memory and
  asset-level recall on the same corpus and queries. The database design guide
  records proposed evaluation thresholds; they are not claims of achieved
  performance.

## References

- [Vector design, fallback and evolution criteria](../database-and-vector-search.md)
- [Product upgrade and backfill](../product-deployment.md)
- [Saved-index implementation](../../services/retrieval/saved_index.py)
- [Vector-store implementation](../../services/retrieval/vector_store.py)
