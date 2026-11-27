# 聊天平台导入实验交接

分支：`codex/chat-import-experiments`，基于 `codex/yuanjian-retrieval-validation` 的 `6ef8db2`。这是实验及失败证据交接，不是可用的一键导入功能。

| 平台 | 本分支内容 | 结果 |
| --- | --- | --- |
| WhatsApp | 静态/动画 WebP 包生成器、独立网页、剪贴板诊断、自动化检查 | iPhone 12 / iOS 16.3.1 Safari 真机仍报错 1000，未导入成功 |
| 微信 | 原 GIF 完整性、Safari 分享静态化、微信内长按发送对照记录 | 长按发送能动；网页一键发送和一键导入未实现 |
| QQ | 公开接口可行性调查 | 未实现、未真机验证 |
| Telegram | 无代码 | 尚未开发、未真机验证 |

先阅读 [WhatsApp 复现步骤与结果](../../docs/whatsapp-web-import-experiment.md)。另见 [微信调查](../../docs/wechat-gif-sharing-investigation.md)、[QQ 调查](../../docs/qq-import-feasibility.md)。

入口是 `/web/whatsapp-import.html`，正式 `/web/` 不链接此页。只有实验页需要新增静态资源白名单，没有新增业务 API 或修改公共字段、数据库、检索及原 `share.js`。页面调用成功仅表示浏览器接受操作，不表示 WhatsApp 已导入；失败结果不得写成成功。

生成的 `web/whatsapp-demo-pack.json`、原 GIF、模型、本机配置、临时公网地址、手机聊天截图均不上传。生成器读取现有演示 GIF，校验 SHA-256，转换后重新解码检查尺寸、帧数和时长。图源为 Google Noto Emoji（CC BY 4.0），测试页保留署名及转换说明。

发布前重新构建并校验了测试包；Python 资源集成测试 4 passed、Edge 浏览器检查 8 passed，Ruff 和 Prettier 通过。自动化检查包含模拟剪贴板分支，不能替代真机验收。直接导入、从贴纸栏发送动画、Android、微信一键发送均没有通过验收。当前不要求用户重复已失败的同类测试。
