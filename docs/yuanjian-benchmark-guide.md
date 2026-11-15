# YuanJian：正式评估准备与交接

2026-11-15。交付分支：`codex/yuanjian-retrieval-validation`。SomersWong 与 Zirui Huang 为同一成员（用户确认）。本工具是检索负责人独立的离线评估工具，不修改正式 API、数据库、agent 契约或网页。此次实际评估采用已有 12 个演示 GIF；下文是将来执行正式 A/B/C 所需的准备说明，不代表这些实验已经执行。

## 当前可运行内容

- `services.retrieval.evaluate_local`：真实 CLIP 演示库首帧/多帧对照，已测首帧 11/12、多帧 12/12。不是正式 A/B/C。
- `services.retrieval.benchmark`：真实样本完整性检查、划分泄漏检查、A/B/C 结果汇总。新加 10 项测试，与索引发布测试合计 11 passed。
- 样本及结果 JSON 是评估工具专用输入，不是给其他模块新增的公共接口字段。接入实际实验时由检索负责人转换正式任务结果，不能要求前后端改变接口。

## 先准备真实样本

在一个独立目录保存 manifest.json、截图和目标 GIF。下面只是单个样本的字段示意，不能直接算合格样本，须替换实际文件、哈希和人工标注：

```json
{
  "version": 1,
  "frozen_at": "由组长确认的实际冻结时间",
  "cases": [{
    "id": "case-001",
    "split": "development",
    "category": "in_library",
    "family_id": "由人工标注的底层GIF或梗图家族",
    "origin": "real_screenshot",
    "reviewer": "实际确认目标的人",
    "image": "inputs/case-001.png",
    "image_sha256": "实际截图SHA256",
    "target": "targets/case-001.gif",
    "target_sha256": "实际目标GIF的SHA256"
  }]
}
```

类别可选 in_library、out_of_library、unknown；unknown 不填 target 和 target_sha256，不当作已知无匹配。split 为 development 或 final。同一 GIF/家族、缩放或抽帧变体不得跨两个集合。final 文件由 Zirui 保管，实现冻结前不要用于调参。工具只能检查提供的家族标签，不能代替人工发现误标的同家族变体。

使用 PowerShell `Get-FileHash -Algorithm SHA256 文件路径` 获取真实哈希（写入 JSON 时小写）。目标 GIF 会实际解码检查多帧，截图会检查格式和哈希；文件不能逃出 manifest 所在目录。

## 组员需确认的最小输入

1. Jiongle：真实截图需求、描述及来源授权；初始固定库；开发集；B/C 同一搜索来源、上限和超时；B 第二轮固定补搜规则；C 的模型/配置；成功门槛。
2. Zirui：隔离保管最终验收集，冻结后揭晓；复核目标动画及同款替代判分。
3. Haoxuan：正式部署的文件与索引边界；Windows 过长路径的部署处理意见。尚未擅改共享存储或系统权限。

来源案例清单目前 eligible_case_count=0。不能把无目标文件、没有真人确认的来源提议当作正式样本。工具会拒绝空集合；不自动生成假的30个需求。

## 执行和统计

在仓库根目录运行（替换实际样本路径）：

```powershell
$py = 'C:\Users\L\.conda\envs\maie6000c-retrieval\python.exe'
& $py -m services.retrieval.benchmark C:\path\to\samples\manifest.json
& $py -m services.retrieval.benchmark C:\path\to\samples\manifest.json --runs C:\path\to\runs.json --output .cache/abc-summary.json
& $py -m pytest -q tests/unit/test_retrieval_benchmark.py tests/unit/test_retrieval_publication.py --basetemp=.cache/bench-tests
```

`runs.json` 是记录数组，每个 case_id/arm 仅一次。重复试验应另存完整实验批次，不能挑最好的一次混在同一批次：

```json
[{
  "case_id": "case-001", "arm": "A", "status": "completed",
  "elapsed_seconds": 1.5,
  "search_calls": 0, "planner_calls": 0, "downloads_used": 0,
  "candidates": [{"sha256": "实际候选文件SHA256", "decoded_multiframe": true}]
}]
```

失败记录 status=failed、candidates=[]，另填 failure_code。候选按实际排名保存，最多三项且 SHA 不重复。decoded_multiframe 必须来自候选实际解码；统计器不会仅凭该标记独立证明收件或下载成功。

统计分 development/final、三种目标类别、A/B/C；输出命中分母、字节精确 Top-3 命中、动画候选数量、p50/p95、调用数、失败分类及缺少的实验项。complete_matrix 只表示每例都有 ABC 记录，不代表实验配置相同、来源公平、30例要求或最终人工验收已经通过。相同动画不同编码可能 SHA 不同，需另附人工判分，不擅自记精确命中。

目前工具不自动执行 A/B/C，也不自动改写现有 agent。正式运行前必须先冻结 B/C 查询规则、初始库/缓存条件和用户何时继续联网的实验规则。可复用现有 `search_web` 的 planner/provider 注入点及 `scripts.verify_gif_acquisition` 保存的候选、trace 和消耗字段；首次发现和收藏后复用分开统计。正式 agent 的候选顺序保持不变。

## 验证与限制

本轮新增 10 项检查测试及既有新索引发布测试：11 passed，Ruff 通过。测试覆盖未知目标不评分、失败留在分母、非动画不计命中、缺失组别可见、重复记录拒绝、预算限制、文件越界/哈希错误/静态目标拒绝、家族跨集拒绝。

尚缺：真实样本、正式完整实验记录、相同预算配置审阅、开发集改进实验、最终盲测、人工判分、收藏/重启/断网端到端复测。原有两项符号链接测试因 WinError 1314 仍未通过；没有关闭安全校验来使测试变绿。正式效果和全链路工作没有宣称完成。
