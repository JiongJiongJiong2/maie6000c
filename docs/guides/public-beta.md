# Run the invitation-only beta rehearsal

English · [简体中文](../public-beta.md) · [All user guides](README.md)

This profile lets an operator rehearse invitation-based registration, screenshot retrieval, original downloads and feedback on their own computer. The website binds to loopback, the database and media fetcher use internal Docker networks, and external searches are disabled. An operator can record feedback locally and decide later when to recruit outside testers.

## Start the rehearsal

Use a Docker Compose plugin that supports `!override` and `!reset`. The rehearsal uses these to publish a single loopback API port and remove the database host port. Check the merged configuration with the `config --quiet` step below. [Compose merge rules](https://docs.docker.com/reference/compose-file/merge/)

On 28 November 2026 the Chrome rehearsal returned 403 for an invalid invitation, 201 for a successful registration and 401 for anonymous access to a private asset. An imported 44-frame GIF ranked first for frame 13. After the API and worker were recreated, a fresh login found the same asset at rank one for frame 29. Both downloaded originals matched the 1,001,718-byte reference file byte for byte. These observations cover this test fixture. The trial protocol below measures outcomes for actual user screenshots. [Browser and restart evidence](../../submissions/week13/public-beta-rehearsal.json)

Use the installation guide to prepare the licensed reference GIFs and the pinned CLIP model, or reuse an existing complete copy. Use PowerShell from a checkout containing the beta changes. The rehearsal gets a separate project name, database and media volume. The first setup generates a database password and an invitation code. Keep this environment file and project name across restarts. [Model and corpus preparation](product-deployment.md#install-with-docker)

```powershell
New-Item -ItemType Directory -Force .cache | Out-Null
if (-not (Test-Path -LiteralPath .cache/public-beta.env)) {
    $dbPassword = [guid]::NewGuid().ToString('N')
    $invite = [guid]::NewGuid().ToString('N')
    @("POSTGRES_PASSWORD=$dbPassword", "BETA_INVITE_CODE=$invite") |
        Set-Content -LiteralPath .cache/public-beta.env -Encoding ascii
}
$beta = @('--env-file', '.cache/public-beta.env', '-p', 'memeretrieve-beta-rehearsal',
          '-f', 'compose.yaml', '-f', 'compose.local-model.yaml',
          '-f', 'compose.pgvector.yaml', '-f', 'compose.public-beta.yaml')
docker compose @beta config --quiet
docker compose @beta build api worker media-fetch
docker compose @beta up -d --wait db
docker compose @beta run --rm --no-deps api alembic upgrade head
docker compose @beta run --rm --no-deps api python -m services.retrieval.vector_store provision
docker compose @beta run --rm --no-deps api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @beta run --rm --no-deps worker python -m services.retrieval.engine index
docker compose @beta up -d --wait
python -m scripts.check_public_beta --local http://127.0.0.1:58095/web/
```

Open the [loopback rehearsal site](http://127.0.0.1:58095/web/). To change the port, set `BETA_HOST_PORT` in `.cache/public-beta.env`. Set `REFERENCE_HOST_PATH` or `CLIP_MODEL_HOST_PATH` if the corpus or weights are elsewhere. Enter `BETA_INVITE_CODE` on the registration form. Existing users can sign in directly. To rotate the reusable code for future registrations, change its value and run `docker compose @beta up -d api`. To pause the rehearsal, run `docker compose @beta stop`.

If the team has a private feedback form, set `BETA_FEEDBACK_URL` to its HTTPS response URL and recreate the API container. If the field is empty, the operator can use the worksheet below. No vision or search provider credentials are required for the local rehearsal.

## Instructions for testers

Choose **Register**, enter a username and password and use the operator’s invitation code. Open **My GIF Library → Import GIFs**, import an animated original you have permission to use and wait for the index to become ready. The prepared reference catalog is also available.

Crop a real screenshot around the target. Remove avatars, usernames and surrounding chat. Choose **Local only**, inspect the first three results, play the target and download it. Tell the observer whether the action, caption and version match. Then try a target absent from the library. If you have the original file, compare it with the download using `Get-FileHash -Algorithm SHA256` on both files.

**Screenshots are uploaded to the host running MemeRetrieve.** In this rehearsal the host is the operator’s computer. In a hosted installation **Local only** searches the server-side private and reference libraries. The worker normally makes temporary task media eligible for cleanup seven days after a task finishes. Saved originals and task records persist. Testers can contact the operator through the agreed private channel for requests about their data. [Storage and cleanup](../backend-guide.md#shared-files-and-persistence)

## Record a trial

The proposed first round collects 30 authorized real requests from 5–10 people. Record the expected original or an independent judge before each search. Keep known in-library targets, known out-of-library targets and uncertain targets separate. Include cropped, compressed and caption-obscured screenshots. Frames from one GIF belong to the same asset family. Record one request per row and use participant aliases. Leave screenshots, chat records and credentials out of the feedback form. For a later comparison of local retrieval, direct description search and agent-planned search, freeze the source, budget, asset-family split and decision rules in advance. [Evaluation protocol in Chinese](../final-closeout-plan.md#效果评估与功能边界)

| Participant alias / case ID | Known in library, out of library or uncertain | Scenario and crop | Original’s rank in top three or miss | Similar but wrong version, empty result or error | Seconds from submission to usable original | Original and download SHA match? | Participant’s comment |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

In-library Top-3 is the number of independently confirmed originals in the first three results divided by all known in-library requests. Include errors, timeouts and misses in the denominator. Report mistaken identifications for absent targets and participant judgments for uncertain targets separately. Show raw numerators and denominators, successful search times and the count of unfinished requests. Before recruiting broadly, have a tester on another device verify registration, saving, retrieval from another frame after restart and a matching original download.

## Opening to external participants

After the local rehearsal, the team lead decides whether to invite external testers and which cohort to invite. The operator provides an actual HTTPS site and a private feedback contact. From an external network open the sign-in page and run `python -m scripts.check_public_beta https://YOUR-DOMAIN/web/`. This checks the sign-in page, API readiness and a 401 response for an anonymous private asset request. Use the browser to verify account isolation, the Secure session cookie behind the proxy, authenticated searches and downloads. Restore a consistent database and media-volume backup in a separate environment before opening access. If access crosses accounts or an original is damaged, pause the external entry point, retain the diagnostic records and revert to a verified release. [Container rollback](container-release.md#roll-back)

For an online cohort, confirm the providers permit that use, set a spending cap and limit registration and search request frequency. Try one authorized GIF from the real website with a remembered source clue. Account for usage from failures as well as successful searches. Keep the rehearsal on its isolated loopback profile until the team has decided to open a separate external installation. [Business pilot proposal](../product/business-model.md)
