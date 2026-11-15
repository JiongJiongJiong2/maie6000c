# YuanJian 网页联调兼容修复

本提交基于 Zirui 的 GIF 分享实现，修正部署和旧浏览器兼容问题；没有新增导入、微信发送或聊天应用集成能力，也没有改变公共 API/数据库字段。

## 改动

- `services/api/app/web.py`：静态资源白名单补上页面已经导入的 `share.js`，避免正式 `/web/` 返回 404；为 JavaScript/CSS 指定响应类型，避免 Windows 注册表把 JavaScript 识别成 `text/plain`；缺失资源返回 404。
- `web/api.js`：增加 `combineSignals`，优先使用原生 `AbortSignal.any`，旧浏览器使用取消信号兼容实现。任一来源取消或调用前已经取消时，都停止对应工作。
- `web/app.js`、`web/meme50.js`：本地和联网结果卡片使用兼容取消信号；换截图和离开结果时继续取消旧请求。
- `tests/integration/test_web.py`：检查资源响应类型、模块可达和 Windows 类型关联干扰。
- `web/tests/mobile-compat.spec.js`：模拟没有 `AbortSignal.any` 的浏览器，检查示例选择器正常初始化，以及取消信号的传播。

## 运行

复用现有 Python retrieval 环境和 `web/node_modules`，无需重新安装。仓库根目录运行：

```powershell
python -m pytest -q tests/integration/test_web.py
python -m ruff check services/api/app/web.py tests/integration/test_web.py
```

先启动项目 API，然后运行浏览器回归。下面的 8000 是本机现有服务端口；其他部署应替换成实际地址。此测试使用 mock API 响应，不要求真实在线搜索供应商。

```powershell
cd web
$env:WEB_BASE_URL='http://127.0.0.1:8000'
$env:PLAYWRIGHT_CHANNEL='msedge'
npm test -- client.spec.js design.spec.js meme50.spec.js mobile-compat.spec.js
npm run format:check
```

使用真实 API 提供页面是为了同时采用正确的模块 MIME；本机 Python 简单静态服务器可能受 Windows 文件类型关联影响。

## 验证边界

发布前资源集成测试 3 passed；上述四个浏览器测试文件在 Edge 中共 27 passed。旧版 Safari 兼容行为由 Edge 中关闭相应能力进行回归，不能当成真实 iPhone WebKit 自动化测试。用户此前已在 iPhone 12 / iOS 16.3.1 Safari 完成示例选择和搜索操作；系统分享的目标应用行为不属于此兼容修复的完成标准。

导入实验及其静态路由不随本提交交付。此变更不解决 Safari 分享 GIF 到微信变成静态图的问题。
