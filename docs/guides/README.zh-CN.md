# MemeRetrieve 使用指南

[English](README.md) · 简体中文

已经拿到站点地址时，直接打开该站点的 `/web/` 并登录。如果要在自己的电脑启动服务，请按下面的部署入口选择。浏览器中的 `127.0.0.1` 指向当前这台电脑。

## 第一次找回动图

点 **Register** 注册。邀请制演练还需要填写运营者提供的邀请码。进入 **My GIF Library → Import GIFs** 导入自己有权使用的原件，等待索引就绪，也可以先用预置的参考样例。

把截图裁到要找的表情范围，选择 PNG、JPEG 或 WebP，在 **Local only** 模式下上传。播放候选，核对动作和字幕，选 **This is the one** 后下载。安装后可用 `data/reference/examples/1f92f.png` 试搜，并将下载与 `data/reference/1f92f.gif` 比较。

如果目标没有出现，且本次部署启用了联网搜索，点 **Continue online**，写下记得的动作或来源。**Search activity** 显示实际搜索进度。选中匹配的联网结果，点 **Confirm and save**。收藏索引就绪后，换一帧截图也可以通过 **Local only** 找回原件。本地检索使用运行网页服务的主机上的图库；联网模式还会把缩放图片或代表帧发给配置的识图供应商。[网页搜索、收藏和下载](../product-deployment.md#用网页找回和收藏-gif)

## 选择部署方式

| 我想做什么 | 使用哪份手册 |
| --- | --- |
| 自行启动带账号、私人库和 pgvector 的完整产品 | [Docker 源码部署和 PostgreSQL 16 迁移](../product-deployment.md) |
| 在自己电脑上做邀请制试用 | [本机公测演练与反馈记录](../public-beta.md) |
| 使用 GitHub Actions 已验证的发布镜像 | [镜像固定、备份和回滚](../container-release.md) |
| 在常规部署启用联网搜索 | [配置 HKUST 或 HKGAI 识图与 DeepSeek 搜索](online-search.zh-CN.md) |
| 使用宿主 Python 运行 API 和 worker | [Windows 快速启动](#用-windows-宿主-python-启动) · [完整中文本地手册](local-demo.zh-CN.md) |

## 用 Windows 宿主 Python 启动

打开 Docker Desktop，在仓库根目录的 PowerShell 执行以下命令。启动器用容器运行 PostgreSQL，并在宿主机上运行 API 和 worker。网页默认使用 8000 端口，按 Ctrl+C 可停止这两个宿主进程。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,retrieval]"
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
$env:HF_HUB_OFFLINE = '1'
.\.venv\Scripts\python.exe -m services.retrieval.engine index
.\.venv\Scripts\python.exe scripts/run_local_demo.py
```

使用原生 PostgreSQL 16 时，解压 Windows x64 二进制包，使 `pg_ctl.exe` 位于 `.cache/pg16/pgsql/bin/pg_ctl.exe`，也可用 `--postgres-bin` 指定二进制目录，用 `.\.venv\Scripts\python.exe scripts/run_windows_demo.py` 替换最后一行。保留 `.cache/w07-postgres` 下的数据供下次使用。要停止数据库，执行 `.\.venv\Scripts\python.exe scripts/run_windows_demo.py --stop-database`。各启动方式共用默认端口，请按所选方式单独启动。[完整本地手册与 Linux、macOS 命令](local-demo.zh-CN.md)

## 常见问题

| 现象 | 首先检查 |
| --- | --- |
| 网页打不开 | 回到启动服务时的 PowerShell，运行 `docker compose @product ps` 或 `docker compose @beta ps`。标准部署默认端口是 8000，本机演练是 58095。 |
| 参考样例没有结果 | 核对注册前是否已导入参考清单，以及 worker 是否已完成索引。私人收藏还需登录原来的账号，并等到 **Index ready**。 |
| 无法联网续搜 | 本机演练使用离线模式。常规部署需启用联网并配置识图供应商与 DeepSeek。已入库的动图可继续本地检索。 |
| 任务一直没有完成 | 联网任务先看 **Search activity**，再在 API 和 worker 日志中按请求或任务 ID 查找执行记录。就绪端点只检查服务状态。 |

产品定位和功能边界见[产品说明](../product/README.zh-CN.md)。其他工程资料可从[仓库首页](../../README.md)进入。
