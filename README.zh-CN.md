# MemeRetrieve

[English](README.md) · 简体中文

用一张截图找回原来的动图。上传裁剪好的 PNG、JPEG 或 WebP，就能搜索参考图库和自己的 GIF 收藏。开启联网功能的部署还可以让搜索 Agent 继续查找，查看搜索进度并收藏原件。收藏建立索引后，即使重启服务并关闭外部搜索，也能用另一帧截图找回它。

| 你想了解什么？ | 简体中文 | English |
| --- | --- | --- |
| 产品能解决什么问题、已验证的能力、局限和商业模式设想 | [产品说明](docs/product/README.zh-CN.md) | [Product](docs/product/README.md) |
| 如何注册、找图、启动 Docker、演练公测或回滚版本 | [使用与部署指南](docs/guides/README.zh-CN.md) | [User and operator guides](docs/guides/README.md) |
| API、后台任务、图片和动画的向量索引、存储及测试 | [技术文档](docs/technical/README.zh-CN.md) | [Technical documentation](docs/technical/README.md) |

## 开始使用

首次安装请跟随 [Docker 部署指南](docs/product-deployment.md)，在部署电脑打开 `http://127.0.0.1:8000/web/`。选择 **Local only**，上传截图并播放候选结果。已启用联网时，可以点 **Continue online** 继续查找，通过 **Confirm and save** 把选中的原件加入私人库。

[邀请制公测演练](docs/public-beta.md)使用单独的本机地址 `http://127.0.0.1:58095/web/`。用运营者提供的邀请码注册。该配置仅搜索库内素材，并关闭外部搜索和 AI 标注。

## 已经验证了什么？

在真实网页验收中，提供来源线索后找回了一份 44 帧 GIF，收藏后重启并关闭外联，用不同帧再次找回，下载文件与原件逐字节一致。在单独的公测演练中，第 13 帧和第 29 帧都把同一份收藏排在第一位，两次下载的 1,001,718 字节均与原件一致。上述记录覆盖指定授权样本；真实用户独立截图的命中率仍待评估。[发布验收](submissions/week13/README.md) · [公测回执](submissions/week13/public-beta-rehearsal.json)

## 仓库结构

浏览器客户端在 [web/](web/)，FastAPI、后台 worker 和检索实现在 [services/](services/)，数据库迁移在 [alembic/](alembic/)。[scripts/](scripts/) 提供启动和验证命令，[tests/](tests/) 保存后端测试，[GitHub Actions](.github/workflows/) 负责构建和验证应用与发布镜像。历史实验、特定来源的记录、课程交付和模板可从[中文文档总目录](docs/README.zh-CN.md)查找。

## 项目来历

Memeory 最初为一位 iPhone 用户设计，让其从精选图库中用截图查找动图。W04 方案、W07 演示和 W13 交付记录了项目如何发展成现在支持账号和私人库的网页产品。[W04 方案](submissions/week04/README.md) · [W07 演示](submissions/week07/README.md) · [W13 交付](submissions/week13/README.md) · [原版仓库介绍](https://github.com/JiongJiongJiong2/maie6000c/blob/03ddad76dda3d63ed95f58e6993ae97830a1d86b/README.md)
