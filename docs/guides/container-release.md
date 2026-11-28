# Deploy the published container images

English · [简体中文](../container-release.md) · [All user guides](README.md)

The release workflow builds Linux CPU images for the API, search worker and media fetcher from the same `main` commit. The image names are `ghcr.io/jiongjiongjiong2/maie6000c-api`, `ghcr.io/jiongjiongjiong2/maie6000c-worker` and `ghcr.io/jiongjiongjiong2/maie6000c-media-fetch`. The `main` tag advances on release. Resolve a verified `git-<full commit SHA>` tag once, then save the three repository digests for upgrades and rollback. Use Docker Compose v2.24.4 or newer for the release overlay’s `!reset` support. This overlay combination was verified with v5.3.1. [Compose merge reference](https://docs.docker.com/reference/compose-file/merge/)

## Pin a verified release

Open PowerShell in the repository root at the revision you intend to deploy. Use the full SHA of a `main` release. The commands below check the GitHub Actions run, pull the three images, verify their OCI revision labels and save their digests in a local env file. If package access is restricted, sign in to GHCR with package-read access and use Docker’s credential store. [GitHub CLI run lookup](https://cli.github.com/manual/gh_run_list) · [GHCR authentication](https://docs.github.com/en/packages/working-with-the-container-registry/working-with-the-container-registry)

```powershell
$sha = '<verified 40-character main commit SHA>'
if ($sha -cnotmatch '^[0-9a-f]{40}$') { throw 'A full commit SHA is required' }
$runs = gh run list --repo JiongJiongJiong2/maie6000c --workflow container-release.yml `
  --branch main --event push --commit $sha --status success --limit 1 `
  --json headSha,conclusion,url | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $runs.headSha -cne $sha -or $runs.conclusion -ne 'success') {
  throw 'No successful release run found for this commit'
}
$runs.url

$components = [ordered]@{
  MEMERETRIEVE_API_IMAGE = 'api'
  MEMERETRIEVE_WORKER_IMAGE = 'worker'
  MEMERETRIEVE_FETCH_IMAGE = 'media-fetch'
}
$imageLines = foreach ($key in $components.Keys) {
  $repository = "ghcr.io/jiongjiongjiong2/maie6000c-$($components[$key])"
  $tag = "${repository}:git-$sha"
  docker pull $tag | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "Image pull failed for $tag" }
  $revision = docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' $tag
  if ($LASTEXITCODE -ne 0 -or $revision -cne $sha) { throw "Revision label mismatch for $tag" }
  $digest = docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' $tag |
    Where-Object { $_ -cmatch ('^' + [regex]::Escape($repository) + '@sha256:[0-9a-f]{64}$') } |
    Select-Object -First 1
  if ($LASTEXITCODE -ne 0 -or -not $digest) { throw "Missing image digest for $tag" }
  "$key=$digest"
}

New-Item -ItemType Directory -Force .cache | Out-Null
$images = ".cache/release-$sha.env"
if (Test-Path -LiteralPath $images) {
  if (((Get-Content -LiteralPath $images) -join "`n") -cne ($imageLines -join "`n")) {
    throw 'Existing release record differs from the resolved digests. Check the record before continuing.'
  }
} else {
  $imageLines | Set-Content -LiteralPath $images -Encoding ascii
}
```

Save the three-image file for each release. For an existing deployment use the original project name from `docker compose ls`, the same `.env`, ports and mounts. For a new installation choose one project name and use it consistently. Apply `compose.release.yaml` last so the application services use the published images with the product deployment’s existing database and storage configuration.

```powershell
$project = 'memeretrieve'  # Use the original project name for an existing deployment.
$deployment = @('-p', $project, '--env-file', '.env',
  '-f', 'compose.yaml', '-f', 'compose.local-model.yaml', '-f', 'compose.pgvector.yaml')
$release = $deployment + @('--env-file', $images, '-f', 'compose.release.yaml')
docker compose @release config --quiet
docker compose @release config --images db api media-fetch worker
```

Check that all three application services use the saved digests. Variables already set in the PowerShell process can override env-file values. If the resolved image list differs, remove or correct the relevant session override and check again.

## First start and acceptance check

Prepare the public reference GIFs, CPU CLIP model and private `.env` using the product guide. Local retrieval needs the database, corpus and cached model. Online vision and web search require their own credentials. Run each command in order and check it succeeds. Import the reference manifest before opening registration so new accounts inherit the reference catalog. [Prepare the model and corpus](product-deployment.md#install-with-docker)

```powershell
docker compose @release pull db api worker media-fetch
docker compose @release up -d --no-build --pull never --wait db
docker compose @release run --rm --no-deps --pull never api alembic upgrade head
docker compose @release run --rm --no-deps --pull never api python -m services.retrieval.vector_store provision
docker compose @release run --rm --no-deps --pull never api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @release run --rm --no-deps --pull never worker python -m services.retrieval.engine index
docker compose @release up -d --no-build --pull never --wait db api media-fetch worker
docker compose @release ps
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Open `/web/` on the port configured in `.env`. Register or sign in and upload `data/reference/examples/1f92f.png` in **Local only**. Let the job complete, play the first candidate, download the GIF and compare its SHA-256 with `data/reference/1f92f.gif`. For release acceptance, use an existing account to verify its collection, restart the services and retrieve the same saved original from another frame. Correlate request IDs and job IDs with `docker compose @release logs --tail 100 api worker media-fetch` to confirm worker completion and the vector backend used.

## Upgrade an existing installation

Retain the three running image digests and the matching Compose files. Set `$previousImages` to the previous release record and keep the project name and deployment settings. When moving from the original PostgreSQL volume to the pgvector volume, restore the logical backup to the separate database volume first. For a first switch from locally built images to a published release, use the old installation’s original Compose arguments for `$prior`; retain the old code and local images for recovery. [Migrate an existing PostgreSQL 16 installation](product-deployment.md#migrate-an-existing-postgresql-16-installation)

```powershell
$previousImages = '.cache/release-<previous full commit SHA>.env'
$prior = $deployment + @('--env-file', $previousImages, '-f', 'compose.release.yaml')
# For a locally built prior deployment, use its original Compose arguments for $prior.
$backup = New-Item -ItemType Directory ('.cache/backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$mediaBackup = 'memeretrieve-backup-' + [guid]::NewGuid().ToString('N')

docker compose @prior stop api worker
if ($LASTEXITCODE -ne 0) { throw 'Failed to pause services' }
docker compose @prior exec -T db pg_dump -Fc -U postgres -d maie6000c -f /tmp/memeretrieve-release.dump
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed' }
docker compose @prior cp db:/tmp/memeretrieve-release.dump "$($backup.FullName)/database.dump"
if ($LASTEXITCODE -ne 0) { throw 'Failed to copy database backup' }
docker compose @prior run -T --no-deps --pull never --name $mediaBackup --entrypoint tar worker `
  -C /data/media -cf /tmp/memeretrieve-media.tar .
if ($LASTEXITCODE -ne 0) { throw 'Media backup failed' }
docker cp "${mediaBackup}:/tmp/memeretrieve-media.tar" "$($backup.FullName)/media.tar"
if ($LASTEXITCODE -ne 0) { throw 'Failed to copy media backup' }
docker rm $mediaBackup
```

Store the backup in a restricted location because it contains accounts and private GIFs. Once the backup and new image digests are verified, run migrations and the acceptance checks above with `$release`. Rebuild the reference index when the corpus, model or index format requires it. If the release introduces new vector tables or workspaces for backfill, provision and backfill them using the migration guide. Preserve the existing `postgres_data` or `pgvector_data`, `task_media` and `model_cache` volumes.

## Roll back

Use the old images directly when the previous release can read the current database schema, index and data. Compare the current Alembic revision with the output of `alembic heads` in the old API image. Once compatibility is confirmed, switch the application services back to the verified `$prior` release.

```powershell
docker compose @release stop api worker media-fetch
docker compose @prior pull api worker media-fetch
docker compose @prior up -d --no-build --pull never --wait db api media-fetch worker
docker compose @prior ps
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

For an incompatible database or storage format, restore `database.dump` and `media.tar` from the same backup into empty volumes in a separate project. Use the previous revision’s Compose files, `$prior` settings and original additional host mounts. In a fresh PowerShell session reconstruct `$deployment` and `$prior` using the previous revision and digest file, then choose unused alternative ports. Run each command only after the preceding one succeeds.

```powershell
$env:API_HOST_PORT = '18000'
$env:POSTGRES_HOST_PORT = '15432'
$backup = Get-Item -LiteralPath '<path to the pre-upgrade backup>'
$restoreProject = 'memeretrieve-restore-' + [guid]::NewGuid().ToString('N')
$restoreMedia = "$restoreProject-media"
$restore = @('-p', $restoreProject) + $prior[2..($prior.Count - 1)]

docker compose @restore pull db api worker media-fetch
docker compose @restore up -d --no-build --pull never --wait db
docker compose @restore cp "$($backup.FullName)/database.dump" db:/tmp/memeretrieve-release.dump
docker compose @restore exec -T db pg_restore --exit-on-error --no-owner -U postgres -d maie6000c /tmp/memeretrieve-release.dump
docker compose @restore run -d --no-deps --pull never --name $restoreMedia --entrypoint sleep worker 300
docker cp "$($backup.FullName)/media.tar" "${restoreMedia}:/tmp/memeretrieve-media.tar"
docker exec $restoreMedia tar -C /data/media -xf /tmp/memeretrieve-media.tar
docker stop $restoreMedia
docker rm $restoreMedia
docker compose @restore run --rm --no-deps --pull never worker python -m services.retrieval.engine index
docker compose @restore up -d --no-build --pull never --wait db api media-fetch worker
```

Run the same browser checks on the alternate API port. Keep the upgraded volumes available for reconciling data written after the backup. Once the restored installation passes acceptance, the operator can switch the user-facing entry point.
