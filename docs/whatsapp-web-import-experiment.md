# WhatsApp 网页直接导入实验（2026-11-15）

目标：不安装额外 App，从 iPhone Safari 直接导入 WhatsApp，保留动画并可重复使用。
用户接受转换成动态贴纸包，不强制保留 GIF 文件格式；手动发送再加星标不等于该目标完成。
这是独立实验，不是已完成的导入功能。源码与失败记录在 `codex/chat-import-experiments` 分支交接，基于检索交付分支提交 `6ef8db2`。没有安装辅助手机 App，也不接入正式搜索页面。

## 实验依据和边界

WhatsApp 官方 iOS 示例要求原生 `UIPasteboard` 写入
`net.whatsapp.third-party.sticker-pack` 格式的 JSON，然后打开 `whatsapp://stickerPack`。
网页实验尝试用 `ClipboardItem` 和 `navigator.clipboard.write` 写入同名类型。
即使浏览器返回写入成功，也不代表原生剪贴板映射正确，更不代表 WhatsApp 已导入。
只有手机出现添加界面、用户确认、贴纸栏可找到并发送动画，才算成功。

- [WhatsApp 官方接口说明](https://github.com/WhatsApp/stickers/blob/main/iOS/README.md)
- [WhatsApp 官方原生调用代码](https://github.com/WhatsApp/stickers/blob/main/iOS/WAStickersThirdParty/Interoperability.swift)
- [WebKit Async Clipboard API](https://webkit.org/blog/10855/async-clipboard-api/)
- [WebKit 自定义剪贴板格式的封装限制](https://webkit.org/blog/8170/clipboard-api-improvements/)

不把普通文本、PNG 或浏览器封装的自定义格式当作 WhatsApp 原生贴纸包。
不在写入失败后跳转 WhatsApp；不自动发送消息。
第 2 版仅在用户主动点击“检查刚写入的数据”后读取剪贴板，检查目标测试类型，
不读取普通文本或图片类型，不展示或上传剪贴板内容。只记录匹配与否、大小或错误信息。
写入可能替换用户已复制的内容，测试页在按钮前明确说明。
原生示例支持 60 秒剪贴板过期，网页不能设置这个原生选项；测试页仅在
60 秒后隐藏打开链接，不能保证剪贴板数据自动清除。

模块影响：`services/api/app/web.py` 静态白名单增加三个精确文件名和对应 MIME 类型。
生成文件不存在时返回 404。没有新增业务 API，没有修改公共请求/响应字段、数据库、
检索模块或原来的 `share.js`，普通 `/web/` 不引入本实验。

## 复现命令（Windows PowerShell）

在仓库根目录激活已有 Python 3.11 项目环境，确保已安装项目依赖、Pillow（支持 WebP）、pytest 和 Ruff，无需重装已有环境。浏览器检查需要 `web/node_modules` 和已安装的 Edge（也可选择本机 Chrome）。以下 `python` 指该项目环境的解释器：

```powershell
python experiments/whatsapp_web_import/build_pack.py
python -m pytest tests/integration/test_web.py -q --basetemp .cache/wa-pytest
python -m ruff check experiments/whatsapp_web_import/build_pack.py services/api/app/web.py tests/integration/test_web.py
```

构建脚本读取已准备好的 `data/reference/manifest.json` 与 GIF，先校验原始 SHA-256，
只生成 `web/whatsapp-demo-pack.json`，不改原文件。生成包已加入 Git 忽略，
新机器需要先用 `python scripts/prepare_demo.py` 准备演示 GIF，再运行构建脚本；已有数据则跳过下载。这里只测试导入，不需要下载 CLIP 模型或重建检索索引。完整字节、帧数和哈希记录在
`.cache/whatsapp-pack-report.json`。

若已有项目 API，更新代码后重启它以加载新增静态入口。没有运行服务时，可在仓库根目录另开终端启动：

```powershell
python -m uvicorn services.api.app.main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/web/whatsapp-import.html`。本实验的静态资源不依赖数据库、worker 或检索模型，不需要先搜索 GIF；完整项目搜索仍需按 `local-demo.md` 启动其余服务。本机私有的 `Start-Test.cmd` 和临时隧道不随 Git 交付。

手机测试须由部署者为同一服务提供证书受信任的 HTTPS 入口，再访问 `/web/whatsapp-import.html`。不要把电脑的 `127.0.0.1` 地址输入手机；访问验证取决于部署配置，不能保证其他环境无需登录。临时域名不作为交付配置。

针对运行中的真实 API 服务测试，避免 Windows 普通静态服务器 JS MIME 不正确：

```powershell
cd web
$env:WEB_BASE_URL = 'http://127.0.0.1:8000'
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm test -- whatsapp-import.spec.js
```

## 发布前复测（2026-11-15）

当前第 3 版重新构建测试包成功，输出仍为 1746849 字节；静态包 44543 字节，动画尺寸、帧数、时长和哈希与下述记录一致。资源集成测试 4 passed，Edge 实验测试 8 passed，Ruff、Prettier 和差异空白检查通过。真实 Edge 剪贴板调用仍拒绝该类型；其他模拟分支只验证网页控制流程。手机失败结论未改变，没有把浏览器回归通过当作导入通过。

## 初版实际验证（历史记录）

- Python 静态入口测试：4 项通过。
- Edge 浏览器实验测试：4 项通过，其中 1 项真实调用系统剪贴板 API，另外包含
  模拟拒绝、模拟写入成功以及测试包缺失的流程检查。模拟写入成功不属于导入验收。
- 真实 Edge 157 返回 `NotAllowedError`：
  `Type net.whatsapp.third-party.sticker-pack not supported on write.`
  页面记录为 `clipboard_rejected`，没有显示打开 WhatsApp 的入口。
- 手机 HTTPS 地址的 HTML 和 JSON 请求均返回 200，内容类型正确，包含 3 个贴纸。
- Ruff 检查通过；原始 GIF 哈希校验通过；转换后重新解码确认动画、尺寸和总时长。

| 演示图 | 动画 WebP 字节 | 帧数 | 时长毫秒 |
| --- | ---: | ---: | ---: |
| Mind blown | 489434 | 83 | 2610 |
| Laughing tears | 472208 | 59 | 1770 |
| Party time | 306056 | 42 | 1380 |

三张均为 512×512、每张不超过 500 KiB，帧时长至少 8 毫秒，包内全为动画。
96×96 PNG 图标为 8714 字节。图源 Google Noto Emoji，CC BY 4.0；已转换格式，
使用有损压缩。这里只检查官方格式限制，不代表 WhatsApp 已实际接受。

## iPhone 真机反馈（2026-11-15 15:24，用户提供截图）

设备：iPhone 12 / iOS 16.3.1 / Safari 16.3；WhatsApp 版本未记录。
页面记录 `secureContext: true`、`clipboardWrite: true`、`clipboardItem: true`，
测试包 1702250 字节。点击第二步后记录
`open_requested_import_unverified`，说明页面的写入调用已返回成功并请求打开应用。
这不证明 WhatsApp 所需的原生剪贴板条目已经存在或内容可被读取。

WhatsApp 实际弹窗：`未能完成操作。（com.third-party-stickers 错误 1000。）`
本次结果：**已打开 WhatsApp，但贴纸包导入失败**。
仅凭此错误码无法判断是剪贴板类型映射、数据传递还是内容校验失败，不能据此
宣称 Safari 完全无法写入，也不能将写入返回成功当作导入成功。

用户此前反馈普通网页分享至 WhatsApp 能作为 GIF 播放。这与添加到贴纸栏是
不同的验收项：普通 GIF 消息成功，不代表贴纸包导入成功。

## 第 2 版真机结果（2026-11-15 15:34，用户反馈及截图）

- A 静态包同样触发 WhatsApp 错误 1000，未完成导入。
- 截图记录 `packKind: static`、`packBytes: 70627`，
  `openDelayMs: 4078`，不是页面规定的 60 秒打开时限超时。
- 手动读回结果为 `test_type_not_visible`，即浏览器没有向页面暴露目标测试类型。
  截图还保留已打开 WhatsApp 的状态，不能确定检查前剪贴板是否被其他操作改变；
  不能把这一结果等同于原生剪贴板完全没有数据，也不能认定已找到错误 1000 的根因。
- 用户另试 WhatsApp 内“创建贴图”，从相册选此前保存的 Party time，提示添加贴图失败。
  这是另一条导入路径的失败，尚无证据表明与网页实验属于同一原因。
- 用户报告可用路径：先把 GIF 发送到聊天，长按 → 更多 → 添加星标，之后能在 GIF 栏找到。
  记为“用户确认 GIF 收藏可见”，不记为贴纸包导入成功。

用户随后确认：从 GIF 星标项再次发送，新消息仍然会动。因此“发送后手动收藏并复用 GIF”
路径通过用户真机验证，不再要求重复这一测试。
用户进一步明确：希望网页直接添加到 WhatsApp 的可复用收藏中，接受保持 GIF 格式，
不要求一定成为贴纸包。这仍不等于先发送再手动加星标；网页自动添加 GIF 收藏未实现。
不能把手动收藏的通过写成直接导入通过。后续发现第 2 版静态数据格式不符合导入协议，
须按下文第 3 版更正解读，不能把静态失败作为有效的格式对照证据。

## 第 3 版：纠正静态包的接口格式（2026-11-15）

重新核对官方文档和 `StickerPack.sendToWhatsApp` 源码发现：虽然源贴纸可接受 PNG，
官方发送方法会使用 `sticker.imageData.webpData`；传递 JSON 中的 `image_data` 要求
WebP，PNG 仅用于 `tray_image`。第 2 版把 PNG 直接放进 `image_data`，这是本实验的错误。
之前“静态包符合接口格式”的判断撤回。不能声称更正前的静态失败证明了浏览器限制。

来源：[官方发送实现](https://github.com/WhatsApp/stickers/blob/main/iOS/WAStickersThirdParty/StickerPack.swift)
和 [官方 JSON 协议](https://github.com/WhatsApp/stickers/blob/main/iOS/README.md)。

已修正：静态控制改为 512×512 单帧 WebP，分别为 6250、12922、5234 字节，
重新解码确认单帧和尺寸；包 JSON 为 44543 字节，identifier 更新为
`maie6000c-web-static-control-v3`。图标仍为 96×96 PNG。动画包从第一版起就是 WebP，
原有动画失败结果不受这项纠正影响。

8 项浏览器检查、Ruff、差异空白检查通过。Edge 的真实调用依旧因不支持原生类型而拒绝。
第 3 版测试时没有改正式分享页，也没有安装额外 App；本次只将实验源码和失败记录交接到独立分支。

第 3 版手机反馈（2026-11-15 15:53，两张 Safari 截图）：
`experimentVersion: 3`、`identifier: maie6000c-web-static-control-v3`、
`packBytes: 44543`，确认已加载修正后的 WebP 静态包。
`readback.result: test_type_not_visible`，浏览器仍未向网页提供目标类型；
`result: open_requested_import_unverified`、`openDelayMs: 4242`，记录已请求打开应用，
未超过页面的 60 秒打开时限。
截图本身没有 WhatsApp 的错误弹窗或添加界面。用户随后明确答复：第 3 版仍然报错 1000。
因此该版本的实际导入结果记为失败；这是用户确认，不是从 Safari 状态推断的结果。

当前结论：在已测 iPhone 12 / iOS 16.3.1 Safari 环境下，修正为 WebP 后的静态包
仍未能通过本网页剪贴板方案导入。原始动画 WebP 包同样失败。不能把失败简单归因为
静态 PNG 格式，也不能只靠错误码确定 WhatsApp 内部原因。
此方案不接入正式 `/web/` 分享流程，不记作交付成功，不要求用户再重复 A/B 测试。
用户要求“不装额外 App、直接导入并可复用动画”的目标仍未实现；当前未找到经验证的
纯网页替代入口。保留实验源码和结果供后续出现新接口或新证据时继续排查。

复测地址：原手机 `/web/` 地址后接 `whatsapp-import.html?v=3`。
确认标题第 3 版，默认 A：点第一步 → 点检查刚写入的数据并记录 → 重新点第一步 →
立即点第二步。将读回安排在跳转之前，避免 WhatsApp 打开后可能改变剪贴板造成混淆。
若修正后 A 仍失败，不要求重复 B；这不是已验证的修复承诺。

额外路线核查：官方已有在 WhatsApp 内创建、分享自定义贴纸包的说明，但未找到允许
普通网页为任意新 GIF 生成可导入贴纸包链接的公开接口。官方贴纸库下载/聊天内分享
不能直接等同于外部网页上传任意包。无依据时不构造未知导入链接或承诺一键成功。

## 第 2 版历史操作记录（已执行，不要求重复）

以下保留当时操作步骤用于解释证据。当前源码为第 3 版，`?v=2` 只改变请求 URL，不会切换回旧版代码或生成旧包，不能用于复现第 2 版实现。

1. iPhone Safari 打开 `whatsapp-import.html?v=2`，确认标题是“第 2 版”，等待加载。
2. 保持默认 A 静态贴纸包，点击第一步，然后在 60 秒内点击第二步。
3. 若 WhatsApp 仍报错 1000，返回 Safari，重新点击第一步，再点击
   “检查刚写入的数据”。若提示粘贴权限，可允许本次检查。截图记录即可，先不重复测 B。
4. 只有 A 能成功添加，才选择 B 动画包重复导入，并确认贴纸栏能发送动画。
5. 提供 WhatsApp 版本以便后续复现；这次没有改原有 GIF 分享入口，无需重测普通 GIF 分享。

第 2 版增加的对照和检查（2026-11-15）：

- A：3 张 512×512 单帧 PNG，分别 15571、20308、8091 字节；每张小于 100 KiB。
  包 JSON 为 70627 字节。仍使用与 B 相同来源，独立包 identifier，不混合静态和动画。
- B：保留上一版动画数据和包 identifier，JSON 为 1702250 字节。
- 资源 JSON 改为实验内部版本 2 的包集合；写入剪贴板时只传选中的标准包对象。
  没有修改业务接口、公共字段或静态入口清单，不需要重启服务。
- 读回使用 SHA-256 比较，只保存匹配结果，不输出哈希或原文。读回完全相同也不代表
  WhatsApp 原生剪贴板格式正确。找不到类型不代表原生数据一定不存在，可能是浏览器不暴露。
- 切换包会撤销旧的打开入口，并丢弃旧检查的异步结果。打开链接时重新检查 60 秒时限。
- 8 项 Edge 浏览器检查通过：真实格式拒绝、模拟写入拒绝、动画包字节格式、加载失败、
  静态包及读回匹配/缺少类型/权限拒绝、切换包时旧结果失效。Ruff 与差异空白检查通过。
  真实 Edge 仍不接受这个原生类型。其余剪贴板分支是模拟检查，不能当作手机导入通过。

判读：A 成功而 B 失败，说明值得继续排查动画数据与大小；A、B 均失败且网页读回
匹配，结果更符合网页到原生应用之间的格式传递问题，但仍不能只凭此证明错误 1000 的根因。
如果对照仍失败，不应不断要求用户重复相同流程或将静态包成功宣称为最终目标完成。

尚未验证：原生剪贴板实际格式、错误 1000 的具体原因、成功添加并从贴纸栏发送动画。
未测试 Android，也未解决微信系统分享静态化问题。
