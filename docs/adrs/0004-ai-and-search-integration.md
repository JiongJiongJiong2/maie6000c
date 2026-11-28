# ADR 0004: Separate online discovery from local visual retrieval

## Status

Implemented; retrospective record, pending team review.

## Context

A screenshot may match a known reference or saved GIF, but the target can also
be outside the local collection. Online discovery, image understanding and
visual ranking have different failure modes, privacy requirements and costs.

## Decision

Use a pinned CLIP model for local frame embeddings and ranking. For the formal
online flow, use HKUST vision by default, with HKGAI as an explicitly
configurable option, and DeepSeek for query planning and web search. Run
provider work through the worker and retrieve public media through a separate
`media-fetch` service. Validate actual media before publishing candidates;
search results or a high similarity score do not establish that the original
GIF was recovered.

The product supports two complementary paths:

1. **Local:** encode the query and compare it with reference and ready saved
   frame indexes. This does not require an online search provider at query
   time, but does require the local model and index.
2. **Online:** use the configured vision and search providers to discover
   sources, fetch and decode media, rank candidates, and expose results for
   user review. The fetch service does not receive model or database
   credentials and is separated from the database network.

The formal image-first workflow can return different media formats. An
animation claim requires actual decoding and frame inspection; a static
candidate must not be described as a recovered multi-frame GIF.

## Alternatives considered

- **Local retrieval only:** works without online providers, but is limited to
  the indexed reference and saved collections.
- **Search text or pages without decoding candidate media:** cheaper to
  integrate, but a page or static image is not evidence of the original
  animation.
- **Other model or search providers:** possible through configuration or
  additional adapters, but differ in credentials, cost, availability and
  evaluation. The repository does not establish a comprehensive provider
  benchmark.

## Consequences

Local search can continue without an online provider once its model and index
are available. Online search requires configured providers and sends image
representations to the configured vision service; deployment must account for
privacy and provider availability. Budgets, timeouts, safe media fetching and
explicit failures bound the workflow, but do not guarantee retrieval quality
or permission to reuse a source. Human review remains necessary.

## Operational implications and reconsideration

- Screenshot representations can leave the machine for vision processing;
  provider credentials, data handling and user expectations must be reviewed
  before enabling online search.
- Calls and downloads have shared budgets and deadlines. A provider failure,
  exhausted budget and genuine no-result outcome need distinct reporting;
  mocks do not establish live provider availability.
- Reconsider the provider or model when documented requirements, privacy,
  latency, cost or independent quality evaluation justify a change. Recheck
  model versions, ranking behavior and provider-specific failure paths.

## References

- [Product workflow and provider setup](../product-deployment.md)
- [meme50 data flow and privacy boundaries](../meme50.md)
- [Model and index design](../database-and-vector-search.md)
- [Online provider configuration](../hkust-deepseek-execution.md)
