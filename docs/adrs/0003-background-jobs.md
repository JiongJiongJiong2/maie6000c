# ADR 0003: Use database-backed jobs and a separate worker

## Status

Implemented; retrospective record, pending team review.

## Context

Search, media retrieval and indexing can take longer than an HTTP request.
Users need durable status, explicit failures and a way to retry without
silently losing previous attempts.

## Decision

The API persists a request and pending job before acknowledging submission.
A separate worker claims pending work using PostgreSQL row locking
(`FOR UPDATE SKIP LOCKED`), performs bounded processing outside the claim
transaction, and records the result or failure. Idempotency keys protect
submission, review, retry and save operations. Interrupted search jobs are
marked failed so that an explicit retry can create a new attempt.

The durable execution boundary is:

1. Validate and persist the input, then commit the request and initial job.
2. Claim a pending job in a short transaction and record that it is running.
3. Perform retrieval or provider calls outside the claim transaction, with
   configured subprocess timeouts.
4. Persist candidates and terminal status together, or record a typed failure.
5. On explicit retry, retain the earlier attempt and create another job.

The worker also processes saved-asset index jobs. Saving a GIF does not mean
that indexing has completed: failure leaves the original saved and exposes a
retryable index state.

## Alternatives considered

- **Do the work in the API request:** fewer components, but slow inference or
  network calls would tie request lifetime to processing.
- **Use an external broker:** useful for more demanding queueing or scaling,
  but adds a service and synchronization boundary to this deployment.
- **In-memory background tasks:** simpler, but queued state would not survive
  process restarts.

These alternatives are recorded to explain the trade-offs; no broker
benchmark is claimed.

## Consequences

Job history and failure state are queryable after restart without a separate
broker. The worker and database must be monitored and operated; polling,
single-worker scheduling and bounded subprocesses limit throughput. A job
completion, user acceptance, durable save and successful indexing are distinct
outcomes.

## Operational implications and reconsideration

- Worker health is separate from API readiness: operators need job state and
  worker logs, not just a successful API health check.
- Startup recovery assumes the documented worker coordination; adding
  parallel workers requires revisiting recovery and claim ownership, not only
  adding processes.
- Consider a dedicated broker when measured queue latency, throughput or
  delivery requirements exceed the current database-backed design. Such a
  change would need a plan for idempotency, job history and recovery.

## References

- [Backend worker and client contracts](../backend-guide.md)
- [Job constraints and claims](../database-and-vector-search.md)
- [Search worker implementation](../../services/worker/app/search_worker.py)
- [Search job integration tests](../../tests/integration/test_search_backend.py)
