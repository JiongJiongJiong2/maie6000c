# 梗图搜索实验 v1

这个版本把“搜索 → 用户检查 → 原图收藏或空白模板加字 → 收藏并生成向量 → 下次检索”接成了可运行的闭环。前端按组员后续接手的要求，仅保留普通表单、图片列表和文字编辑框。它是独立实验入口，不依赖 W07 的 PostgreSQL、worker 或固定 GIF 语料库，也不改变 W07 页面。

## 启动

在仓库根目录使用 Python 3.11。当前机器的 `.venv` 和离线 CLIP 权重已准备好：

```powershell
.venv/Scripts/python.exe scripts/run_meme_agent.py
```

打开 <http://127.0.0.1:8010/studio/>。进程关闭后重新运行同一命令，收藏会恢复。需要隔离测试数据时使用 `--port 8011 --data-root .cache/meme-agent-ui-test`。启动器固定监听本机地址，默认一个进程。

新机器先准备环境：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[retrieval,dev]"
.venv/Scripts/python.exe scripts/download_model.py
```

Linux/macOS 对应使用 `.venv/bin/python`。图片推理只读 `data/models/clip-vit-base-patch32` 的固定版本权重，不会在运行时自动下载。Windows 使用微软雅黑；Linux 中文编辑需安装 Noto CJK 字体，或设置 `MEME_FONT_PATH` 指向字体文件。

将 [配置示例](../experiments/meme_search/mvp.env.example) 中需要的项目写入本机 `.env`。DeepSeek key 只在服务端读取，浏览器只能看到是否配置；401/超时会回退到少量本地别名。`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL` 可覆盖；本次官方 `/models` 返回 `deepseek-flash`、`deepseek-v4-pro`，实测使用前者。不配置 key 也可以用 `Drake`、`Two Buttons` 等模板名操作。

## 操作与实际范围

搜索“上面拒绝下面赞同的 Drake”，检查来源、画面、实际格式和帧数。可直接确认收藏，也可在空白模板上输入顶部/底部文字，生成新候选后再确认收藏。导入自己的图片也先产生未收藏候选；只有明确勾选“无文字的静态空白模板”才能加字。当前是固定上下文字布局，没有去字、自由排版或 GIF 编辑。

确认收藏时，服务保存图片元数据和真实 CLIP 图像向量；编码失败不会显示收藏成功。相同字节按 SHA-256 去重，编辑结果保留原模板 ID、来源和文字。截图查询使用 CLIP 向量余弦相似度；文字查询本地收藏使用标题、原搜索词和字幕的关键词匹配，并非文本语义向量检索。GIF 可以导入收藏，但向量仅使用第一帧。候选排序不代表概率或“肯定是同一张图”。

默认联网来源是 [Imgflip 热门模板目录](https://imgflip.com/api)，不是全站、中文表情包全库或全网反向搜图。DeepSeek 仅接收文字描述以规划搜索词；它在此流程中不接收截图，也不直接提供图片。可配置 [Brave 图片搜索](https://api-dashboard.search.brave.com/app/documentation/image-search/get-started)，但本版只接受 `i.imgflip.com` 和 `i.imgur.com` 的 HTTPS 图片，其他来源会跳过。Brave 路径仅有模拟契约测试，尚未用真实 key 验证。下一轮应先验证所需中文来源及其持久化使用条件，再扩大来源。

这是有步骤和工具边界的应用工作流：查询规划、目录/搜索 API、媒体验证、编辑、收藏。工具目前通过 Python 函数和 HTTP API 接入，没有声称使用了 MCP server 或执行了外部 skill。后续若加入 MCP，可以替换 provider 边界，复用相同的下载验证和入库确认，不让模型输出直接写收藏库。

## 数据与接手位置

`data/meme-agent/library.sqlite3` 保存候选元数据、收藏标记、模型版本、float32 向量；`data/meme-agent/media/` 保存原始字节。SQLite 中直接计算余弦排序适合这个小规模实验，没有部署专用向量数据库。未确认候选不会进入向量索引，超过 48 小时的未收藏素材会在下次启动时清理；已收藏作品引用的原模板保留。截图只在请求中读取，不保存为图库素材。数据目录、`.env`、浏览器测试截图均被 git 忽略。

同一服务的浏览器会话共用这一个收藏库，可以验证“下一个人复用上一个人确认的素材”的数据路径；尚无账户、权限、审核或公网部署。不要把本机验证称为跨用户产品验收。

| 位置 | 职责 |
| --- | --- |
| `web/studio/` | 简单原生 HTML/CSS/JS，组员可独立替换样式 |
| `services/meme_agent/app.py` | FastAPI 接口、请求编排；`/docs` 可查看接口 |
| `services/meme_agent/providers.py` | DeepSeek 查询词规划、Imgflip、可选 Brave |
| `services/meme_agent/media.py` | 来源限制、重定向检查、下载限额、真实解码 |
| `services/meme_agent/editor.py` | 本机静态图片加字 |
| `services/meme_agent/library.py` | SQLite 持久化、确认去重、真实向量检索 |
| `services/retrieval/encoder.py` | 复用 W07 的离线 CLIP 模型 |

候选最多下载 6 张，媒体限 12 MiB、2400 万像素、200 帧，总解码像素也有限额。下载检查公开 IP 和受支持的 HTTPS 域名，每次重定向重新检查；DNS 检查与 HTTP 连接仍是分开的，因此不是通用抗 DNS 重绑定的任意 URL 下载器。此限制也是第一版只允许少量受信 CDN 的原因。

## 验证

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check services/meme_agent scripts/run_meme_agent.py tests/test_meme_agent_api.py tests/test_meme_agent_library.py tests/test_meme_agent_providers.py
```

真实浏览器检查需要在 `web/` 安装锁定的前端开发依赖（`npm ci`）及本机 Chrome。先启动独立测试数据目录的 8011 服务，再在仓库根目录运行：

```powershell
node scripts/verify_meme_agent.mjs
```

这个检查会发真实模型/目录请求并保存一张测试图；不要指向正在使用的收藏库。输出在 `.cache/meme-agent-verification/`，不提交图片和本机数据库。[验证摘要](../experiments/meme_search/mvp_validation.json) 记录本次结果。缩放后截图找回自身只验证闭环和近重复复用，不能推导任意网络截图识别准确率。

后续优先补中文来源覆盖、同款空白模板对应关系和小规模真实用户成功率，再决定接入专用向量数据库、完整 MCP 适配或多用户服务。
