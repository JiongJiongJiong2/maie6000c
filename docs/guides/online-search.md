# Configure online search

English · [简体中文](online-search.zh-CN.md) · [User and operator guides](README.md)

Use this guide with the regular account-based deployment. The invite-only loopback rehearsal deliberately disables external calls. Local retrieval needs the reference corpus, CLIP and indexes; online retrieval also needs a vision provider, DeepSeek and the separate media-fetch service. The selected vision service receives a resized image or representative frames, and DeepSeek uses the queries to search the web.

## Select the providers

From the repository root, activate the project’s Python 3.11 environment. Choose **one** vision command. HKUST is the default. A production HKGAI key works with the HKGAI option.

```sh
python -m scripts.configure_meme50 --provider hkust --vision-only
```

```sh
python -m scripts.configure_meme50 --provider hkgai --vision-only
```

Enter the key at the interactive prompt, then configure DeepSeek and check which configuration is present. The helper writes the project’s local `.env`. The check makes no provider request.

```sh
python -m scripts.configure_meme50 --deepseek-only
python -m scripts.configure_meme50 --check
```

With the regular Docker deployment, set `ONLINE_SEARCH_ENABLED=true`. Recreate the API and worker with the same project name, env file and Compose overlays used at startup. In the PowerShell shell from the [Docker guide](product-deployment.md), run `docker compose @product up -d --wait api worker media-fetch`. A native deployment needs its API and worker processes restarted to read the new environment.

## Verify from the website

Sign in at `/web/`, upload an authorized screenshot using **Local only**, then select **Continue online** if the target is missing. Add a clue you genuinely know, such as the source site or what moves in the animation. **Search activity** shows progress. Play the candidate before choosing **Confirm and save**, wait for the index to finish and try a different frame locally. To verify exact recovery, compare the downloaded GIF’s SHA-256 with an independently obtained original.

A disabled online option is expected in the rehearsal. On a regular deployment with a failed task, first check the actual API/worker environment, worker job status and the media-fetch service. Missing credentials, an unavailable source and a completed search that missed the target require different follow-up. The [recorded browser run](../evidence/gif-acquisition/hkgai-web-offline-20261128.json) includes both successful recovery and earlier misses.
