# Operations Notes

## Local startup

1. copy `.env.example` to `.env`
2. set `POSTGRES_PASSWORD` in `.env` to a private hexadecimal value
3. run `docker compose --profile starter up --build` for the starter flow
4. open the API docs if desired
5. submit a case through the API
6. confirm the worker processes the job

For MemeRetrieve, the default `docker compose up --build` instead starts the
search worker. Follow the [backend guide](backend-guide.md) for corpus import,
search contracts, shared-file retention, and backend verification.

## Health endpoints

- API live: `/health/live`
- API ready: `/health/ready`
- AI live: `/health/live`
- AI ready: `/health/ready`

## Metrics

- API metrics: `/metrics`
- AI metrics: `/metrics`
- Prometheus: enable the `observability` profile

## Common useful commands

- run tests: `pytest -q`
- run smoke tests: `SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q`
- run migrations: `docker compose run --rm api alembic upgrade head`
- seed demo data: `docker compose run --rm api python scripts/seed_demo_data.py`

## Failure handling in the starter

If AI processing fails:

- the job is marked failed
- the case is marked failed
- the error is recorded on the job row

## Resetting local state

To remove local database state:

- `docker compose down -v --remove-orphans`
