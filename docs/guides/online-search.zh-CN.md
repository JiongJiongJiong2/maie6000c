# 配置联网搜索

[English](online-search.md) · 简体中文 · [使用与部署指南](README.zh-CN.md)

本指南适用于常规账号部署。邀请制本机演练配置已关闭外部调用。本地检索需要参考库、CLIP 模型及索引；联网还需要一个识图供应商、DeepSeek 和独立的媒体抓取服务。选定的识图服务会收到缩放后的截图或代表帧，DeepSeek 根据查询搜索网页。

## 选择供应商

在仓库根目录激活项目的 Python 3.11 虚拟环境。以下两个识图命令任选一个。默认使用 HKUST；HKGAI 生产凭据使用第二条命令。

```sh
python -m scripts.configure_meme50 --provider hkust --vision-only
```

```sh
python -m scripts.configure_meme50 --provider hkgai --vision-only
```

在交互提示中输入凭据，再配置 DeepSeek 并检查当前配置。脚本写入项目本地的 `.env`，检查命令只核对配置是否存在。

```sh
python -m scripts.configure_meme50 --deepseek-only
python -m scripts.configure_meme50 --check
```

常规 Docker 部署中设置 `ONLINE_SEARCH_ENABLED=true`，使用启动时相同的 Compose 项目名、环境文件及配置组合重新创建 API 和 worker。在[部署指南](../product-deployment.md)所用的 PowerShell 会话中执行 `docker compose @product up -d --wait api worker media-fetch`。原生部署请重启 API 和 worker，让进程读取新配置。

## 从正式网页验证

登录 `/web/`，用 **Local only** 上传一张有权用于测试的截图。若未找到目标，点 **Continue online**，补充自己确实知道的来源或动作线索。**Search activity** 显示实际进度。先播放候选动画，再点 **Confirm and save**；索引就绪后换一帧本地查找。需要验证原件时，将下载文件与独立留存的原 GIF 比对 SHA-256。

本机演练中联网选项会禁用。若常规部署上的任务失败，先核对 API 和 worker 实际读取的配置、任务状态及媒体抓取服务。凭据缺失、来源不可达、已完成查询但未命中原件，需要分别排查。[正式网页的成功与未命中记录](../evidence/gif-acquisition/hkgai-web-offline-20261128.json)
