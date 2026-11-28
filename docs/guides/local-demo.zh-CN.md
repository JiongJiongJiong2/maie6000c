# 本地端到端演示（W07）

[English](../local-demo.md) · 简体中文 · [使用指南目录](README.zh-CN.md)

本页保留 W07 的宿主机运行方案及当时的验收范围。Zirui 的网页、Haoxuan 的 API 与 PostgreSQL 任务队列，通过独立 worker 调用基于 YuanJian 图像编码器的 CLIP 检索适配器。演示对 12 份已署名的动态 GIF 运行真实推理，网页走正式上传和检索接口。当前产品的账号、私人库、pgvector 和全容器部署见[产品部署手册](../product-deployment.md)。

## 启动

使用 Python 3.11。浏览器测试另需 Node.js 20 或更高版本。先启动 Docker Desktop，由它运行 PostgreSQL，然后从仓库根目录执行以下命令。macOS 和 Linux 可使用 Bash。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,retrieval]'
.venv/bin/python scripts/prepare_demo.py
.venv/bin/python scripts/download_model.py
HF_HUB_OFFLINE=1 .venv/bin/python -m services.retrieval.engine index
.venv/bin/python scripts/run_local_demo.py
```

打开[本机网页](http://127.0.0.1:8000/web/)。首次准备约需下载 600 MB 模型权重。准备完成后，再次启动只需最后一行。启动器应用数据库迁移、导入素材清单，并分别启动 API 和 worker 进程。PostgreSQL 使用独立的 `memeretrieve-local` Compose 项目和持久卷，监听 `127.0.0.1:55432`，与课程基础容器分开。

启动器在 Git 忽略的 `.cache/local-demo.env` 下保存随机生成的数据库密码，设置存储目录的绝对路径，并启用示例选择器。此 W07 本机配置把 API 绑定到 `127.0.0.1:8000`，以无需设备令牌的方式运行。其他部署可以启用后端令牌认证。准备阶段会获取模型和公开素材。此演示的本地上传、推理和排序都在运行服务的主机上处理截图。

在启动器中按 Ctrl+C 停止 API 和 worker，数据库仍可继续使用。需要暂停数据库时，以下命令保留数据卷。

```bash
docker compose -p memeretrieve-local --env-file .cache/local-demo.env stop db
```

### Windows PowerShell

在仓库根目录运行以下等效命令。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,retrieval]"
.\.venv\Scripts\python.exe scripts/prepare_demo.py
.\.venv\Scripts\python.exe scripts/download_model.py
$env:HF_HUB_OFFLINE = "1"
.\.venv\Scripts\python.exe -m services.retrieval.engine index
.\.venv\Scripts\python.exe scripts/run_local_demo.py
```

运行 `.\.venv\Scripts\python.exe -m pytest -q` 进行 Python 测试，运行 `.\.venv\Scripts\python.exe -m ruff check .` 做静态检查。在 `web/` 中运行下文的 npm 浏览器实测前，先设置 `$env:WEB_BASE_URL = "http://127.0.0.1:8000"`、`$env:WEB_LIVE_DEMO = "1"`、`$env:PLAYWRIGHT_CHANNEL = "chrome"`。

### Windows 原生 PostgreSQL

2026 年 10 月 29 日制作演示文稿时，Docker Desktop 的运行时套接字未能初始化，当次改用原生 PostgreSQL 16.15。从 EDB 获取 Windows x64 PostgreSQL 16 二进制压缩包，将其中的 `pgsql` 目录解压至 `.cache/pg16/`。沿用上面的模型与素材准备步骤，启动原生服务。[EDB 下载页](https://www.enterprisedb.com/download-postgresql-binaries)

```powershell
.\.venv\Scripts\python.exe scripts/run_windows_demo.py
```

启动器使用 `.cache/local-demo.env` 的本机密码，在回环端口 55432 运行 PostgreSQL，执行迁移、导入素材，再启动同一套 API 和独立 worker。集群保存在 `.cache/w07-postgres`，由当前用户的进程运行。原生与 Docker 方案使用相同的默认端口，同一时间只启动一套。

按 Ctrl+C 停止 API 和 worker。要暂停数据库且保留记录，在已准备好的虚拟环境运行 `python scripts/run_windows_demo.py --stop-database`。将 `.cache/w07-postgres` 作为持久数据保留，重启验收会再次使用。PostgreSQL 二进制压缩包留在本机。

## 浏览器演示

1. 在网页向下找到 **Okay, show us the evidence.** 区域。
2. 上传 PNG、JPEG 或 WebP 裁剪图，或展开 **No screenshot? Borrow some evidence.** 选择表情。选择器将图库的实际抽帧作为普通 PNG 上传。
3. 点 **Find my GIF**。API 保存输入，建立待处理任务。独立 worker 领取任务，运行本机 CLIP 推理并保存候选排名。
4. 点 **This is the one** 记录选择，再点 **Download GIF** 获取原始多帧动画。
5. 刷新页面可恢复当前浏览器的检索。**Start a new search** 可以上传下一张，**None of these match** 可记录此次没有命中。

`data/reference/examples/` 中也有独立 PNG 文件，例如 `1f92f.png`（Mind blown）、`1f47b.png`（Boo crew）和 `1f916.png`（Robot friend）。这个 W07 配置只查询 12 份参考 GIF，任意互联网截图可能在本库找不到原件。

## 检索与素材来源

模型为 CLIP ViT-B/32，固定版本 `37000f5cdccec47a3f6f83142bff131370757470`。程序从 safetensors 权重加载模型，通过 Transformers 的 CLIP 图像特征接口在 CPU 上推理。[模型](https://huggingface.co/openai/clip-vit-base-patch32) · [Transformers CLIP 接口](https://huggingface.co/docs/transformers/model_doc/clip)

动画来自 Google 的 Noto Animated Emoji，许可为 CC BY 4.0。项目保留下载的原始 GIF 字节，将抽取的帧合成在白色背景上作为 PNG 示例。仓库的来源清单保存标题、来源地址和 SHA-256 校验和。如果上游文件发生变化，准备脚本会在校验时退出。素材 UUID 由来源地址生成，清单、索引和数据库均使用同一个 UUID。[Google Noto 动画](https://googlefonts.github.io/noto-emoji-animation/) · [Google 许可说明](https://developers.googleblog.com/en/updates-to-emoji-new-characters-new-animation-new-color-customization-and-more/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · [项目素材清单](../demo-corpus.json)

每份 GIF 均匀抽取 8 帧，12 份素材共生成 96 个归一化向量。每次查询都重新计算截图向量，以各个 GIF 的最佳帧相似度对不同原件排序。余弦相似度达到 `0.82` 的候选最多返回 3 份。启动前可用 `RETRIEVAL_MIN_SIMILARITY` 调整这一实验阈值，其数值尚未经概率校准。库外图片仍可能得到相似候选。

索引保存模型版本、素材集版本和清单校验和。若版本或校验和失效，需重建索引。推理使用本机模型文件。12 份示例查询均派生自同一批入库动画，可用于检验库内检索。更大素材库、全新真实截图和更广的表情检索仍需独立评估。

## 验证与排错

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/verify_local_demo.py
cd web
npm ci
WEB_BASE_URL=http://127.0.0.1:8000 WEB_LIVE_DEMO=1 PLAYWRIGHT_CHANNEL=chrome \
  npm test -- client.spec.js design.spec.js live.spec.js
```

真实浏览器测试上传截图、等待推理、确认匹配、恢复选择，并比对下载文件与源 GIF 的 SHA-256，也覆盖选择示例和记录未命中。常规前端测试使用隔离网络样本检查错误处理与恢复。W07 时作者留存的运行记录和当次 CI 分别计数，当时尚待独立复现。较早的 PR #3 Actions 记录为 60 项 Python 通过、1 项跳过、16 项浏览器检查。后续同版复测结果归入 W07 交付记录。[作者验证记录](../local-demo-verification.json) · [W07 交付材料](../../submissions/week07/README.md)

`.cache/local-api.log` 与 `.cache/local-worker.log` 含请求和任务 ID。模型、参考 GIF、上传文件和索引保存在 Git 忽略的 `data/` 下，数据库记录保存在 Docker 卷内，重启 API 或 worker 后可复用。8000 端口已被早先的预览服务占用时，先关闭该实例。模型或索引不可用时，worker 会记录失败任务；重新执行相应准备步骤后再测。

作者记录的 W07 环境由宿主 Python 进程连接容器内 PostgreSQL。全套应用容器、部署加固、真机 iPhone 保存和团队最终验收是不同验证范围。基础 Docker 镜像未安装可选的检索依赖；运行全容器 worker 需包含该依赖，并挂载已准备的模型和索引。当前的容器方案见[产品部署](../product-deployment.md)。

## W07 集成记录

后端基线为 `origin/feature/w07-backend` 的 `501969f4ee11fb2d03c09c96c8744d3118824a67`，编码器基线为 `origin/feature/w07-retrieval` 的 `37ba4d2`。当时的完整集成在 `codex/w07-fullstack-demo` 上准备提交 `dev` 评审，保留后端及编码器提交的原作者。此项工作未执行课程提交或创建里程碑标签。

Codex 集成现有模块，补齐本地检索、索引准备及示例控件，并运行了报告中的检查。Zirui 在发布当时完成本机浏览器演练，团队最终验收与代码评审当时待完成。

`codex/w07-integration` 延用 PR #3 的引擎与索引接口，并参考 YuanJian 在 PR #4 的原型调整验证覆盖。PR #4 的单独 CSV 和索引格式保留作历史设计。该阶段留有 CPU 推理回执，当时计划在具备可用 Docker 的主机上再复现完整数据库流程。后来的产品验收另有记录。[W07 集成验证](../w07-integration-verification.json) · [W13 交付与验收](../../submissions/week13/README.md)
