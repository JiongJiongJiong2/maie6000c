# MemeRetrieve 公测准备

本轮在运营者电脑上演练邀请注册、截图检索、原件下载和反馈收集。浏览器和服务器可以在同一台电脑上使用。专用 Compose 配置把网页绑定到回环地址，把数据库和抓取服务放在容器内部网络，并关闭联网搜索。模拟反馈可以记在本机；外部用户招募和收费试点另行决定。

## 在自己的电脑启动

2026 年 11 月 28 日的本机 Chrome 演练中，错误邀请码返回 403，正确邀请码注册返回 201，匿名访问私人库返回 401。导入授权的 44 帧 GIF 后，第 13 帧截图命中首位。重建 API 和 worker、重新登录后，第 29 帧截图仍命中同一资产首位，两次网页下载均与原件的 1,001,718 字节逐字节一致。该结果覆盖工程流程；真实参与者的成功率还需按下文记录。[本机演练回执](../submissions/week13/public-beta-rehearsal.json)

先按[产品安装指南](product-deployment.md)准备授权参考 GIF 和固定版本的 CLIP。若已有完整素材和权重可直接复用。以下 PowerShell 命令从含本次公测改动的仓库根目录执行，使用单独的 Compose 项目、数据库和媒体卷。第一次生成数据库密码与本地邀请码。已有配置请保留，切换项目名会得到另一套数据。

```powershell
New-Item -ItemType Directory -Force .cache | Out-Null
if (-not (Test-Path -LiteralPath .cache/public-beta.env)) {
    $dbPassword = [guid]::NewGuid().ToString('N')
    $invite = [guid]::NewGuid().ToString('N')
    @("POSTGRES_PASSWORD=$dbPassword", "BETA_INVITE_CODE=$invite") |
        Set-Content -LiteralPath .cache/public-beta.env -Encoding ascii
}
$beta = @('--env-file', '.cache/public-beta.env', '-p', 'memeretrieve-beta-rehearsal',
          '-f', 'compose.yaml', '-f', 'compose.local-model.yaml',
          '-f', 'compose.pgvector.yaml', '-f', 'compose.public-beta.yaml')
docker compose @beta config --quiet
docker compose @beta build api worker media-fetch
docker compose @beta up -d --wait db
docker compose @beta run --rm --no-deps api alembic upgrade head
docker compose @beta run --rm --no-deps api python -m services.retrieval.vector_store provision
docker compose @beta run --rm --no-deps api python -m services.common.reference_assets /data/reference/manifest.json
docker compose @beta run --rm --no-deps worker python -m services.retrieval.engine index
docker compose @beta up -d --wait
python -m scripts.check_public_beta --local http://127.0.0.1:58095/web/
```

默认入口为 [本机公测演练页](http://127.0.0.1:58095/web/)。改端口可在该 env 文件内设置 `BETA_HOST_PORT`。素材在其他目录时可分别设置 `REFERENCE_HOST_PATH` 与 `CLIP_MODEL_HOST_PATH`。演练中只需把 `BETA_INVITE_CODE` 的值输进注册页。已有账号直接登录，更换邀请码后用 `docker compose @beta up -d api` 应用。邀请码可重复使用，换码只影响之后的注册。日常暂停用 `docker compose @beta stop`。

如已建好团队私有收件表单，可在 env 文件里设置 `BETA_FEEDBACK_URL` 为表单的 HTTPS 填写地址并重建 API 容器；留空时可直接用下面的记录表进行现场访谈。首次启动、登录、搜索和下载都可以在没有供应商密钥的环境演练。

## 给第一位测试者

点 **Register**，选择用户名、设置密码并输入运营者给的邀请码。进入 **My GIF Library → Import GIFs**，导入一份有权使用的原始动画，等到索引显示就绪。也可以先用站内参考样本熟悉界面。

选一张真实截图，只裁出想找的表情，去掉头像、昵称和对话。上传后执行 **Local only**。查看前三个结果，播放目标并下载。请用自己的话告诉观察员找到的是同一个动作、字幕和版本，还是仅有相似内容。接着可以用一张图库里没有的图试一次。原件文件在手时，运营者可用 `Get-FileHash -Algorithm SHA256` 分别核对原件和下载文件。

**截图会上传到运行 MemeRetrieve 的服务器。** 此演练服务器位于本机；以后若使用托管版，“Local only”仍指服务器上的私人库与参考库。任务临时媒体默认在任务结束七天后进入后台清理。收藏的原件和任务记录保存在持久卷。参与者若需处理自己的数据，通过运营者约定的私密渠道提出请求。[持久化与清理](backend-guide.md#shared-files-and-persistence)

## 记录一轮试用

第一轮建议用 5–10 人积累 30 个有授权的真实需求。提前记录期望的原件或由谁判定。把已知库内、已知库外、目标未知分开统计，压缩、裁剪、字幕遮挡都保留。相同 GIF 的多个抽帧作为同一素材家族。观察员用下表一行记一次需求，反馈表只收化名和结果。请勿把原始截图、聊天记录、密码或邀请码附在反馈中。未来如果比较本地、直接描述、Agent 规划三种做法，按原评测协议冻结来源、预算、素材家族及判定方式。[效果评估协议](final-closeout-plan.md#效果评估与功能边界)

| 测试者代号 / 案例号 | 已知库内 / 库外 / 未知 | 场景与裁剪特点 | 前三名中原件排名或未命中 | 相似但错版 / 无候选 / 故障 | 从提交到可用原件的秒数 | 下载与参考 SHA 是否相同 | 用户一句话反馈 |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |

库内 Top-3 用“前三名出现经独立确认的原件数 ÷ 所有已知库内需求数”。故障、超时、未命中都进分母。库外单列被误认成原件的次数，目标未知单列用户评价。汇报原始分子、分母，成功耗时和未完成数分别报告。首次开放前建议另一台设备独立完成注册、收藏、重启后换帧检索，以及原件下载核对。

## 何时可以邀请外部用户

本地演练通过后，由团队负责人决定是否开放、开放给谁。运维负责人需先交付实际 HTTPS 地址及私密反馈联系人，用外部网络访问登录页并运行 `python -m scripts.check_public_beta https://实际域名/web/`。脚本核对登录页、API 就绪和匿名访问私人资源返回 401。账户隔离、代理后的 Secure 会话 Cookie、登录后真实搜索和下载仍要用浏览器验收。先做数据库与媒体的一致备份并在独立环境恢复；发现越权或原件损坏时暂停对外入口、保留诊断记录并回到上一验证版。[发布和回滚](container-release.md)

联网测试另需运营者确认供应商允许该批用户使用、设置费用上限、限制注册与搜索请求频率，然后用一份授权素材从真实网页完成一次带来源提示的找回。用量和失败任务一并记账。在批准开放并完成以上验证之前，本机演练保持回环地址与隔离网络。商业招募、报价与后续实验见[商业模式方案](business-model.md)。
