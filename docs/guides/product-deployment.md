# Use and deploy MemeRetrieve

English · [简体中文](../product-deployment.md) · [All user guides](README.md)

Open the installed site at `/web/`. The standard local installation uses [the website on port 8000](http://127.0.0.1:8000/web/). Choose **Register**, enter a username and a password of at least eight characters, and use **Sign in** on later visits. **Sign out** ends the current session. Each account has its own workspace for imports, saved GIFs and search history.

## Find and save a GIF

Upload a cropped PNG, JPEG or WebP screenshot. **Local only** searches the reference catalog and the current account’s indexed GIFs. If the target is missing and online search is enabled, choose **Continue online**. Describe the action, the scene or a source you remember. The operator must configure a vision provider and DeepSeek for online searches. **Search activity** shows the call counts and query plan. When the job finishes you can inspect the queries executed and the number of sources returned.

Play candidates to check the animation. On an online result, choose **Confirm and save** and wait for indexing. On a local result, choose **This is the one** and download the original. **My GIF Library** supports bulk import, management and downloading. Try another frame from the same GIF to retrieve it locally. On a device that supports file sharing, **Share GIF** opens the system share sheet.

## Install with Docker

Use Python 3.11 and Docker Compose v2. From the repository root, open PowerShell and prepare the licensed reference GIFs and pinned CLIP model. The same files can be used on later starts.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

On a new installation set `POSTGRES_PASSWORD` in `.env` to a random alphanumeric password. On an existing installation retain the current environment file and credentials. The product Compose configuration enables accounts and the private library. If an old env file overrides these settings, set `ACCOUNT_LOGIN_ENABLED=true` and `PRIVATE_LIBRARY_ENABLED=true`. A working local retrieval setup needs the model and reference assets. To enable ordinary online searches, configure the default HKUST vision gateway or the optional HKGAI gateway along with DeepSeek. Verify authorized credentials through `python -m scripts.configure_meme50 --check` in the project environment. [Configure vision and search](online-search.md)

```powershell
$product = @('-f', 'compose.yaml', '-f', 'compose.local-model.yaml', '-f', 'compose.pgvector.yaml')
docker compose @product up -d --wait db
docker compose @product build api worker media-fetch
docker compose @product run --rm --no-deps api alembic upgrade head
docker compose @product run --rm --no-deps api python -m services.retrieval.vector_store provision
docker compose @product run --rm --no-deps api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @product run --rm --no-deps worker python -m services.retrieval.engine index
docker compose @product up -d --wait
docker compose @product ps
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Import the reference manifest before users register. The API serves the website, accounts, sessions, jobs and downloads. The worker handles CLIP inference, online search, saved-asset indexing and local retrieval. PostgreSQL 16 holds accounts, jobs, saved-asset state and pgvector frame vectors. Original GIFs and NPZ indexes for saved assets live in the persistent media volume. A separate fetch service retrieves public media. For remote access serve the web client and API under one HTTPS origin and configure the proxy to forward the HTTPS scheme.

Start again with `docker compose @product up -d --wait` and stop with `docker compose @product stop`. Use `docker compose @product logs -f api worker` to follow a save or search job. In local search logs, `vector_backend` identifies the backend for private GIFs and `reference_vector_backend` identifies the backend for the shared catalog. Indexed assets remain searchable in **Local only** mode when an online provider is unavailable.

## Migrate an existing PostgreSQL 16 installation

Keep the existing Compose project name. Stop writes, back up the database and the media volume at the same point, and retain the old database volume. The pgvector configuration uses its own `pgvector_data` volume. Restore a logical dump of the old database into an empty pgvector database so account schemas, asset IDs and receipts carry over. The commands below assume the old database runs in Compose. For a host PostgreSQL installation, use its matching `pg_dump` and `pg_restore`. See the release guide for a media-volume backup procedure. [Back up an installation](container-release.md#upgrade-an-existing-installation)

```powershell
New-Item -ItemType Directory -Force .cache
docker compose stop worker api
docker compose exec -T db pg_dump -Fc -U postgres -d maie6000c -f /tmp/memeretrieve.dump
docker compose cp db:/tmp/memeretrieve.dump ./.cache/memeretrieve.dump
docker compose @product up -d --wait db
docker compose @product cp ./.cache/memeretrieve.dump db:/tmp/memeretrieve.dump
docker compose @product exec -T db pg_restore --exit-on-error --no-owner -U postgres -d maie6000c /tmp/memeretrieve.dump
docker compose @product run --rm --no-deps api alembic upgrade head
docker compose @product run --rm --no-deps api python -m services.retrieval.vector_store provision
docker compose @product run --rm --no-deps api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @product run --rm --no-deps worker python -m services.retrieval.engine index
```

List workspaces with `docker compose @product exec -T db psql -U postgres -d maie6000c -c "SELECT workspace FROM library_accounts ORDER BY workspace"`. Backfill `public` and then each listed `acct_…` workspace. Replace the final `public` in the first command below with the exact workspace name for each run.

```powershell
docker compose @product run --rm --no-deps worker python -m services.retrieval.saved_index --workspace public
docker compose @product up -d --wait
```

The backfill reads validated saved-asset NPZ indexes, verifies the original files and index versions, and mirrors their frame vectors into PostgreSQL. Check that the reported `ready` and `mirrored` counts match. To bind a legacy single-user library to a new account, obtain a one-time setup code with `docker compose @product exec -T api python -m services.common.accounts`, open `/web/sign-in#setup=<code>` and choose **Register**. Existing account holders can sign in directly.

After migration, sign in with an existing account and verify its collection and originals. Save a new GIF, restart the API and worker, and look it up again with another frame. To select the NPZ backend explicitly, set `VECTOR_BACKEND=npz` in `.env` and run `docker compose @product up -d --force-recreate worker`. Keep the same project and media volume.
