# How to use MemeRetrieve

English · [简体中文](README.zh-CN.md)

If someone gave you a site address, open its `/web/` page and sign in. If you are starting the service on your own computer, choose an installation guide below. A `127.0.0.1` link opens a service running on the computer where you click it.

## Find your first GIF

Choose **Register** for a new account. The invitation-only rehearsal also asks for the operator’s code. Open **My GIF Library → Import GIFs** and import an original GIF you can use, or start with a prepared reference GIF. Wait until the imported asset’s index is ready.

Crop a PNG, JPEG or WebP screenshot around the image you want. Choose **Local only** and submit. Play the candidates to compare the motion and caption. Choose **This is the one** to enable the download. To check the standard installation with a known example, upload `data/reference/examples/1f92f.png` and compare the download with `data/reference/1f92f.gif`.

If the original is missing and the operator has enabled online search, choose **Continue online** and add a remembered detail about the motion or source. **Search activity** shows the work as it runs. Choose **Confirm and save** on a matching online result. Once indexing finishes, another frame of the GIF can find the saved original through **Local only**. Local searches use the library on the server hosting the site. Online searches also send a resized image or representative frames to the configured vision provider. [Search, save and download](product-deployment.md#find-and-save-a-gif)

## Choose an installation

| I want to… | Read |
| --- | --- |
| Run the application with accounts, a private library and pgvector | [Install from source with Docker or migrate PostgreSQL 16](product-deployment.md) |
| Rehearse invitation-only testing on my computer | [Start the isolated beta and record tester feedback](public-beta.md) |
| Run an image built and verified by GitHub Actions | [Pin a release, back up the installation and roll back](container-release.md) |
| Enable online search on a regular deployment | [Configure HKUST or HKGAI vision and DeepSeek search](online-search.md) |
| Run the API and worker with host Python | [Windows host launcher](#use-host-python-on-windows) |

## Use host Python on Windows

With Docker Desktop running, use the following commands from the repository root. The launcher runs PostgreSQL in a container and starts the API and worker as host processes. Open the website on port 8000. Stop the host processes with Ctrl+C.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,retrieval]"
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
$env:HF_HUB_OFFLINE = '1'
.\.venv\Scripts\python.exe -m services.retrieval.engine index
.\.venv\Scripts\python.exe scripts/run_local_demo.py
```

To use native PostgreSQL 16, extract the Windows x64 PostgreSQL archive so `pg_ctl.exe` is at `.cache/pg16/pgsql/bin/pg_ctl.exe` (or pass `--postgres-bin` with the path to the binary directory), then run `.\.venv\Scripts\python.exe scripts/run_windows_demo.py` in place of the last command. Keep the database directory `.cache/w07-postgres` for subsequent sessions. Stop its database with `.\.venv\Scripts\python.exe scripts/run_windows_demo.py --stop-database`. Only one launcher can use the default ports at a time. [Native setup, Linux and macOS instructions](../local-demo.md)

## When something goes wrong

| Symptom | First check |
| --- | --- |
| The page will not open | Check the project with `docker compose @product ps` or `docker compose @beta ps` in the PowerShell session used to start it. The standard API port defaults to 8000. The rehearsal port defaults to 58095. |
| A reference screenshot has no matches | Check the reference manifest was imported before registration and the worker completed the index build. For a private GIF, sign in to the account that imported it and wait for **Index ready**. |
| Online search is unavailable | The rehearsal operates offline. A regular deployment needs online search enabled and both a vision provider and DeepSeek configured. Existing library searches remain available. |
| A job appears stuck | Open **Search activity** for an online job. Match its request or job ID in the API and worker logs. A healthy HTTP endpoint alone cannot establish a worker completed a job. |

For the product’s capabilities or the engineering design, use the [product overview](../product/README.md) or the [repository home](../../README.md).
