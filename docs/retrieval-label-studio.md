# 用 Label Studio 做 GIF 人工盲评

在本机运行开源 Label Studio Community Edition 1.23.2。每项任务显示一张查询截图、一份可选原版参照和一份匿名候选。候选按评审项目独立打乱，任务数据只带数据集、案例和候选代号。检索模型、排名和分数留在评估负责人的映射中。

## 打开现有部署

自动评测已用预留原文件核对精确命中，运行时无需登录这里。仅当团队要报告人工判断时才分配评审。可以先挑同样的 10 个截图与候选组合给两人试评，用 `case_id` 和 `candidate_id` 对齐；两个项目顺序不同，各自打开前十条会拿到不同的题。这 10 对只用于核对判分标准。两个 `127.0.0.1` 项目地址都在运行服务的电脑上，组员可轮流使用这台电脑独立作答。

在本机打开 [Label Studio](http://127.0.0.1:58631/)，用 `.cache/label-studio/login.local.json` 的 `email` 和 `password` 登录。该文件只保存在本地，`token` 供导入脚本调用本机 API。导入命令会输出各评审项目的链接。进入分配的项目，点击 **Label All Tasks** 开始逐项判断。两人各用一个项目独立评审，等两份意见提交后再交换结果。此 Community Edition 部署使用一个本机协调员账号，各项目可在项目列表中查看。

请选择 `exact`（能够确认是同一版本）、`variant`（相近但字幕、剪辑或版本不同）、`wrong`（不匹配）、`unsure`（证据不足）或 `broken`（候选无法加载或播放）。评审是在画面、动作和文字上核对版本，程序另行核对字节级 SHA-256。无候选的检索没有标注卡片，仍保留在整体检索结果中。项目的 **Export → JSON** 保留 `data.dataset_id`、`data.case_id`、`data.candidate_id` 和 `annotations[].result[]` 中 `from_name=gif_match` 的 `value.choices`，可按三个代号合并两份导出。取消的标注和空白行作为未完成处理。

## 在 Windows 启动和导入

首次在仓库根目录用 `uv` 创建一个独立的 Python 3.11 环境，并安装指定版本。

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.cache/label-studio/uv-cache'
uv venv --python 3.11 .cache/label-studio/py311
uv pip install --python .cache/label-studio/py311/Scripts/python.exe label-studio==1.23.2
```

启动会生成本地登录文件。保留这个终端和 `.cache/label-studio/app`，其中 SQLite 保存项目、任务和实际提交的标注。用 Ctrl+C 停止前台运行的服务。

```powershell
.cache/label-studio/py311/Scripts/python.exe scripts/retrieval_label_studio.py start
```

另开终端，传入评审清单。清单的 `query_url`、可选 `reference_url` 和候选 `media_url` 均为相对本清单且位于相邻 `media` 文件夹中的路径。脚本只复制实际引用的媒体，用内容哈希命名并从 `127.0.0.1:58632` 供应。项目 API 使用 `127.0.0.1:58631`。重跑同一导入会复用两位评审的现有项目。

```powershell
.cache/label-studio/py311/Scripts/python.exe scripts/retrieval_label_studio.py import `
  --manifest .cache/meme-eval-cn-review/site/review.json
```

标注界面使用 Label Studio 原生配置，启动和导入使用本地 SQLite 与项目 API。 [界面配置](../scripts/label_studio_gif_review.xml) · [官方安装](https://labelstud.io/guide/install.html) · [官方导出](https://labelstud.io/guide/export)

两位评审完成后，分别从各自项目导出标准 JSON，在本机运行以下命令。输出包含两人都已判定的分母、一致率、未判数和待裁决的案例。意见相同但都选了“无法确认”或“无法加载”也进入复核。不要用这些优先挑选的案例推算所有题的真实用户接受率。

```powershell
.venv/Scripts/python.exe -m scripts.compare_retrieval_judgments .cache/meme-eval-cn-review/review-key.json .cache/reviewer-a.json .cache/reviewer-b.json .cache/adjudication.json
```
