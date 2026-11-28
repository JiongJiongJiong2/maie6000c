# 使用已发布的容器镜像

## English overview

This runbook deploys the API, worker, and isolated media-fetch images published
from one verified `main` commit. It verifies the successful GitHub Actions
release, the commit label on each image, and its immutable digest, then records
the digests for reproducible startup, upgrade, and rollback. Keep the existing
Compose project name, `.env`, database and media volumes. Back up PostgreSQL
and media together before an upgrade. Detailed PowerShell commands follow in
Chinese; see the [product deployment guide](product-deployment.md) for initial
setup and data migration.

容器发布流程为同一 `main` 提交生成 Linux CPU 镜像。API、worker 和媒体抓取服务分别发布到 `ghcr.io/jiongjiongjiong2/maie6000c-api`、`ghcr.io/jiongjiongjiong2/maie6000c-worker` 和 `ghcr.io/jiongjiongjiong2/maie6000c-media-fetch`。`main` 标签随发布更新。下面用 `git-<完整提交 SHA>` 找到镜像并记录 digest，升级和回滚均使用保存的 digest。使用支持 `!reset` 的 Docker Compose 插件。本文命令可用于 Compose v2.24.4 及更新版本，组合配置在 v5.3.1 验证。 [Compose 叠加文件](https://docs.docker.com/reference/compose-file/merge/)

## 固定一组已经验证的镜像

从仓库根目录打开 PowerShell。选择已经通过发布流程的 `main` 完整 SHA，并使用该版本的 Compose 文件。先核对 GitHub Actions 运行的状态和提交，再拉取三份镜像。私有包需要有包读取权的 GHCR 登录，凭据交给 Docker 凭据存储管理。 [GitHub CLI 运行查询](https://cli.github.com/manual/gh_run_list) · [GHCR 认证和拉取](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

```powershell
$sha = '<已验证的 40 位 main 提交 SHA>'
if ($sha -cnotmatch '^[0-9a-f]{40}$') { throw '需要完整提交 SHA' }
$runs = gh run list --repo JiongJiongJiong2/maie6000c --workflow container-release.yml `
  --branch main --event push --commit $sha --status success --limit 1 `
  --json headSha,conclusion,url | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $runs.headSha -cne $sha -or $runs.conclusion -ne 'success') {
  throw '找不到这一提交的成功发布记录'
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
  if ($LASTEXITCODE -ne 0) { throw "拉取失败 $tag" }
  $revision = docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' $tag
  if ($LASTEXITCODE -ne 0 -or $revision -cne $sha) { throw "提交标签不匹配 $tag" }
  $digest = docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' $tag |
    Where-Object { $_ -cmatch ('^' + [regex]::Escape($repository) + '@sha256:[0-9a-f]{64}$') } |
    Select-Object -First 1
  if ($LASTEXITCODE -ne 0 -or -not $digest) { throw "缺少镜像 digest $tag" }
  "$key=$digest"
}

New-Item -ItemType Directory -Force .cache | Out-Null
$images = ".cache/release-$sha.env"
if (Test-Path -LiteralPath $images) {
  if (((Get-Content -LiteralPath $images) -join "`n") -cne ($imageLines -join "`n")) {
    throw '已有记录与新解析的 digest 不同，请核对后再继续'
  }
} else {
  $imageLines | Set-Content -LiteralPath $images -Encoding ascii
}
```

保留这份只含三个镜像地址的文件，后续也保留上一版本的对应文件。已有部署沿用 `docker compose ls` 中的项目名，以及原有 `.env`、端口和挂载路径。新安装可选一个项目名，用同一名字完成初始化和后续启动。`compose.release.yaml` 放在最后，数据库和挂载配置沿用产品部署文件。

```powershell
$project = 'memeretrieve'  # 已有部署填写原来的项目名
$deployment = @('-p', $project, '--env-file', '.env',
  '-f', 'compose.yaml', '-f', 'compose.local-model.yaml', '-f', 'compose.pgvector.yaml')
$release = $deployment + @('--env-file', $images, '-f', 'compose.release.yaml')
docker compose @release config --quiet
docker compose @release config --images db api media-fetch worker
```

核对后三个应用服务采用保存的 digest。PowerShell 中已有的同名环境变量可覆盖文件，发现不一致时先清除对应变量再核对。

## 首次启动和验收

按 [产品部署指南](product-deployment.md#首次启动-docker-版本) 准备公开参考 GIF、CPU CLIP 模型和私有 `.env`。本地搜索启动依赖数据库、素材和缓存模型，联网识图及搜索的凭据按需要另行配置。逐条运行以下命令，每条成功后再继续。API 开始接收注册前先导入参考清单，使新账号可以看到初始参考库。

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

使用 `.env` 中实际设置的端口打开 `/web/`。注册或登录后，通过 **Local only** 上传 `data/reference/examples/1f92f.png`。检查任务完成、首个候选可以播放及下载，并与 `data/reference/1f92f.gif` 比对 SHA-256。正式交付再用已有账号验证收藏，在重启后用另一帧回搜同一原件。通过 `docker compose @release logs --tail 100 api worker media-fetch` 根据请求 ID 和任务 ID 核对 worker 完成及实际使用的向量后端。

## 升级已有部署

先保存已经运行的三份镜像 digest 与对应的 Compose 文件。下面的 `$previousImages` 指向上一版的镜像记录，使用相同的 Compose 配置和项目名。若从普通 PostgreSQL 卷切换至 pgvector 卷，先按 [旧库逻辑迁移](product-deployment.md#升级已有-postgresql-16-安装) 将备份恢复到独立卷。应用镜像升级沿用这次部署已有的数据库与媒体卷。

```powershell
$previousImages = '.cache/release-<上一版本完整 SHA>.env'
$prior = $deployment + @('--env-file', $previousImages, '-f', 'compose.release.yaml')
$backup = New-Item -ItemType Directory ('.cache/backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$mediaBackup = 'memeretrieve-backup-' + [guid]::NewGuid().ToString('N')

docker compose @prior stop api worker
if ($LASTEXITCODE -ne 0) { throw '暂停服务失败' }
docker compose @prior exec -T db pg_dump -Fc -U postgres -d maie6000c -f /tmp/memeretrieve-release.dump
if ($LASTEXITCODE -ne 0) { throw '数据库备份失败' }
docker compose @prior cp db:/tmp/memeretrieve-release.dump "$($backup.FullName)/database.dump"
if ($LASTEXITCODE -ne 0) { throw '数据库备份复制失败' }
docker compose @prior run -T --no-deps --pull never --name $mediaBackup --entrypoint tar worker `
  -C /data/media -cf /tmp/memeretrieve-media.tar .
if ($LASTEXITCODE -ne 0) { throw '媒体备份失败' }
docker cp "${mediaBackup}:/tmp/memeretrieve-media.tar" "$($backup.FullName)/media.tar"
if ($LASTEXITCODE -ne 0) { throw '媒体备份复制失败' }
docker rm $mediaBackup
```

备份包含账号和私人 GIF，保存到权限受控位置。核对备份及新镜像之后，以新 `$release` 运行迁移和页首的启动验收。只在参考素材、检索模型或索引格式要求时重建参考索引。有新增的向量表或待回填空间时，按 [旧库逻辑迁移](product-deployment.md#升级已有-postgresql-16-安装) 核对 provision 和回填。保留 `postgres_data` 或 `pgvector_data`、`task_media` 和 `model_cache` 这些现有持久卷。

## 回滚

上一版与当前 Alembic schema 兼容时，可恢复三份旧镜像。先核对当前数据库迁移版本和旧 API 镜像中的 `alembic heads`，并确认上一版读取当前索引和数据的兼容性。使用上一版的 `$prior` 参数。

```powershell
docker compose @release stop api worker media-fetch
docker compose @prior pull api worker media-fetch
docker compose @prior up -d --no-build --pull never --wait db api media-fetch worker
docker compose @prior ps
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

schema 或数据格式有不兼容变更时，用上一版配置在独立 Compose 项目和空卷中恢复同一时间点的 `database.dump` 与 `media.tar`。在新 PowerShell 会话中使用上一版源代码的配置、`$prior` 参数和原额外挂载。将下面的备用端口换成主机上的空闲端口。逐条运行，每条成功后再继续。

```powershell
$env:API_HOST_PORT = '18000'
$env:POSTGRES_HOST_PORT = '15432'
$backup = Get-Item -LiteralPath '<升级前备份目录>'
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

用备用 API 端口运行相同的网页验收。保留升级后的卷供后续核对新增数据，验收通过后再由部署者切换访问入口。
