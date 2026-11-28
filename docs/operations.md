# Operations notes

> **Scope / 范围:** This page combines current operational pointers with W07-era local-launch details and historical verification records. The [product deployment guide](product-deployment.md) is the source of truth for setting up the current account-based product.
>
> 本文汇总当前运维入口、W07 本地启动细节和历史验证记录。当前账户产品的部署步骤以[产品部署指南](product-deployment.md)为准。

For the current web application, open `/web/`. The **Local only** mode uses the reference library and the current account’s ready saved assets. **Continue online** sends the screenshot to the selected vision provider and searches via DeepSeek. The default vision service is HKUST; HKGAI is available through an explicit policy. The public media fetcher processes external sources separately. See [provider configuration](hkust-deepseek-execution.md), [database and storage lifecycle](database-and-vector-search.md), and [the W13 demo](../submissions/week13/README.md).

The Windows native launcher starts PostgreSQL, API, worker, and the media fetcher. The fetcher binds to loopback port 8120 and receives only the host process variables it needs. The Docker-based local launcher also exposes its isolated fetch service on loopback. For an account-based demo, enable both `ACCOUNT_LOGIN_ENABLED` and `PRIVATE_LIBRARY_ENABLED`. For resolver environments that return non-public addresses for public media sites, `MEME50_DNS_MODE=doh` uses the supported public DNS resolution mode with peer and TLS verification. The default system resolver remains available.

## Enable Telegram GIF collection

Set `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` in the API environment using the
credentials from [Telegram API development tools](https://my.telegram.org/apps).
Account mode uses the existing MemeRetrieve session and private workspace. For a
local single-user deployment with account mode disabled, set `DEVICE_TOKEN`.
The Compose API image includes the Telegram dependencies. For a native API
installation, run `python -m pip install -e ".[telegram]"`.

Open `/web/` over HTTPS on the phone. Route `/web/`, `/auth/`, `/telegram/`,
and the other API paths to the same service. Preserve the external `Host` and
have the proxy replace the incoming `X-Forwarded-Proto` with `https`. Set
`FORWARDED_ALLOW_IPS` in the API container to the address of the proxy. This
feature keeps sessions in the API process and requires a single API process.

On a GIF candidate, tap **Add to Telegram GIFs**. Choose a country or region
code and enter the local phone number, or paste the complete international
number. Switch to Telegram to get the code and return to the same browser tab.
The connection lasts up to 15 minutes. Reloading the page requires authorization
again. Disconnecting from the page or signing out of MemeRetrieve ends the
browser's Telegram session.

## Add GIFs to Discord Stickers

### Use on a phone

1. Open MemeRetrieve and sign in with an account enabled for Discord. Find an animated GIF in
   search results or open **My GIF Library**. In a local search, select **This is the one** first.
2. Tap **Add to Discord Stickers**. The GIF is added to the named server’s shared sticker library,
   where members can use it. The page shows **Added to Discord** and the sticker’s name.
   **Already in Discord** means the server already has that GIF and you can use the existing sticker.
3. Tap **Open Discord server** and sign in to Discord with an account that belongs to the server.
   In a channel where you can send messages, open the expression
   picker beside the message field and select **Stickers**. Find the sticker by the name shown
   on the web page and tap it to send. [Discord custom stickers guide](https://support.discord.com/hc/en-us/articles/4403089981975-Custom-Stickers-FAQ)

If the button is missing, check that you signed in with an enabled account and picked an animated
GIF. If the page reports a full sticker library, a server admin can free up a slot. For an
interrupted connection, tap **Retry adding to Discord**. The server checks for the GIF before
creating a sticker, so retrying after a lost response uses the existing slot.

### Configure the Discord server

1. Create an app in the [Discord Developer Portal](https://discord.com/developers/applications).
   In **Installation**, enable **Guild Install**, add the `bot` scope and select
   **Create Expressions**. Use the install link to authorize the app on the destination server.
2. Enable **Developer Mode** in Discord, then right-click the server icon and choose
   **Copy Server ID**. [Discord guide to finding IDs](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID)
3. In the API environment, enable `ACCOUNT_LOGIN_ENABLED`. Set `DISCORD_BOT_TOKEN`,
   `DISCORD_STICKER_GUILD_ID` and `DISCORD_STICKER_ACCOUNTS`. The last value is a JSON list of
   MemeRetrieve usernames, such as `["tester"]`. Set `DISCORD_STICKER_GUILD_NAME` to show the
   server’s display name on the button card. Keep the bot token in the API environment.
4. Restart the API. Run a single API process so simultaneous requests for the same GIF are
   serialized. Sign in with an enabled account and follow the phone workflow above.

Discord accepts animated stickers up to 512 KiB, five seconds and 320 × 320 pixels. When needed,
MemeRetrieve resizes or trims the copy uploaded to Discord and keeps the original GIF in the
library. [Discord sticker API](https://docs.discord.com/developers/resources/sticker#create-guild-sticker)

## Local verification

The W07 supported local profile runs host Python API and worker processes with Docker PostgreSQL. Follow [the local demo guide](local-demo.md), including PowerShell commands, preparation, and verification. Python 3.11 and Docker Desktop are required; Node.js is needed for browser tests. Model weights, corpus, and index must be prepared before startup. The base application Docker image lacks the optional retrieval dependencies and is not the verified inference deployment.

The runner applies migrations, imports the corpus, creates an ignored random-password environment file, and starts separate API/worker processes. API: `http://127.0.0.1:8000`; web: `/web/`; database: loopback port 55432 in the `memeretrieve-local` Compose project. Stop the runner with Ctrl+C. Stop PostgreSQL without deleting records using:

```text
docker compose -p memeretrieve-local --env-file .cache/local-demo.env stop db
```

`/health/live` checks API liveness; `/health/ready` checks dependencies. Readiness alone does not prove worker progress or successful inference. Check persisted job transitions and `.cache/local-api.log` / `.cache/local-worker.log`, correlated by request/job IDs. Missing models or stale indexes require preparation/reindexing; execution failures should persist a failed job, not synthetic results.

Database data lives in a persistent Docker volume; GIFs, uploads, model cache, and index live in ignored host paths under `data/`. Keep both for restart checks. Volume deletion is destructive and is not a routine stop command. Never commit local environment files or downloaded weights.

See [the backend guide](backend-guide.md) for migrations, API contracts, retention, and PostgreSQL verification. The [starter guide](starter-guide.md) documents the historical case/triage flow and its separate AI service, enabled with the starter Compose profile. Those AI health/metrics endpoints do not describe the W07 in-worker CLIP module.

When Docker Desktop is unavailable on Windows, the [native PostgreSQL profile](local-demo.md#windows-without-docker) runs the same API and worker using `scripts/run_windows_demo.py`. It keeps its cluster at `.cache/w07-postgres`, binds to loopback port 55432, and uses the existing ignored environment file. Retain this directory as persistent data. Use `--stop-database` for a non-destructive database shutdown. Avoid concurrent launchers or another database on the same port.

The [fresh W07 evidence](../submissions/week07/assets/run-summary.json) records real browser upload, persisted candidates/review, original GIF download and health. The separate [restart check](../submissions/week07/assets/earlier-request-restart-check.json) records an unchanged result after API/worker restart. This native PostgreSQL run is distinct from the [prior author verification record](local-demo-verification.json). Final team acceptance remains pending. CI fixture tests do not establish live model behavior.
