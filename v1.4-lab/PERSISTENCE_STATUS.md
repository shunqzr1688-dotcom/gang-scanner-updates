# GANG V1.4 交接包与保存状态

更新日期：2026-11-07（Asia/Shanghai）。仅开发分支，不是正式发布。

GitHub 正常连接已完成，目标仓库确认 push 权限；首次开发分支推送已由远程 refs 读取确认，远程提交为 `35d382d585169eeb3eae602fc753462336ffab6c`，包含 `1001f98380f34cdcc61f0793d11ff71864854224` 原提交历史。main 保持 `7046750f604df1b6a8f3a86666564b37981acd5f`。

本提交归档原样的 `archives/gang-v14-acceptance-handoff.zip`（340,263 字节），SHA256：

```text
2d7ea13f4255a6bedfae4c17238c8ab0705191c17c7f781023a20684caa21d48
```

包内包含原测试包、源代码、测试证据、说明、全量 Git bundle，已在此前独立离线恢复核验。归档文件按字节保留，未重打包或改写。该 ZIP 及 `ACCEPTANCE_FOLLOWUP.md` 中认证失败/未远程保存的描述是归档时的历史状态，不代表后续连接与推送结果。

远程文件已从固定提交 `8eb2af2740d1cdfede520363aaa92380ec97a588` 独立重新下载：HTTP 200，340,263 字节，SHA256 与上文一致，ZIP 和全部内层校验清单均通过。已确认工作区之外的 GitHub 保存成功，回执见 `evidence/persistence-receipt.json`。本轮只做归档/哈希/远程 refs 核验，未重跑已有 Linux 测试。

[直接下载原样完整交接包](https://raw.githubusercontent.com/shunqzr1688-dotcom/gang-scanner-updates/8eb2af2740d1cdfede520363aaa92380ec97a588/v1.4-lab/archives/gang-v14-acceptance-handoff.zip)。

获取方式：在当前开发分支进入 `v1.4-lab/archives/gang-v14-acceptance-handoff.zip`，选择 Download raw file。`archives/SHA256SUMS.txt` 是对应的校验清单。若要固定版本，请采用保存回执中的完整 commit SHA 和下载 URL。

本轮没有重跑已有 Linux 测试，也没有修改更新器或业务代码。Windows 11 实机、真实业务脱敏集成及真实断电验收仍未通过；不允许正式部署。后续 Windows 入口仍为 `Run-Windows11-Acceptance.cmd`，独立测试机要求见 README。
