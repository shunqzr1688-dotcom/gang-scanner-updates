# GANG V1.4 继续验收及保存核查报告

检查日期：2026-11-07T03:23:50.510089+08:00。结论：**不得上线；工作区外持久保存尚未完成。**

## 已核实的保存情况

- 提交 `1001f98380f34cdcc61f0793d11ff71864854224` 完整存在，本地分支 `dev/v14-release-prep`。
- 原完整测试包 96,323 字节，SHA256：`7faca3d20fe06ca8029992e8f268f3c6fad4830e4b5924cd53d74b14e91c5758`；ZIP 校验和包内 SHA256SUMS 全部通过。
- 原增量 Git bundle 校验通过，但依赖基线 main。新增 `archives/gang-v14-1001f98-full.bundle` 为全量自包含 bundle；已在独立空目录离线 clone 并验证目标 commit 和更新器源码哈希，无需原仓库、网络或认证。
- 原 ZIP 按字节原样归档到 `archives/gang-v14-release-prep-1001f98.zip`。这些文件将随本地开发分支后续提交保存，便于认证恢复后一次推送。
- **以上都是同一云工作区内的副本，不是云清理之外的备份，不保证工作区销毁后的可恢复性。** 必须成功推送并读取远程验证，或者下载到工作区之外后才能认定持久保存完成。

## GitHub 推送实证

仅向现有仓库的 `refs/heads/dev/v14-release-prep` 执行非强制推送，未操作 main、合并、发布或部署：

1. Git 默认凭证推送：退出 128，`fatal: unable to get password from user`。
2. GitHub CLI 仓库读取：HTTP 401 `Bad credentials`。
3. 使用 `gh auth git-credential` 的 Git 推送：退出 128，`Invalid username or token / Authentication failed`。
4. 推送后公开 API 仍只列出 main，SHA 为 `7046750f604df1b6a8f3a86666564b37981acd5f`；不存在远程开发分支。
5. GitHub 连接未安装/连接，已提供连接入口。当前结论是**本会话没有可用写入认证**，不能据此判断用户账户本身的权限。无需在聊天提供 Token；应使用受支持的 GitHub 连接并授权目标仓库。

## 本轮重新执行的可核查测试

本轮从原 ZIP 解包到独立临时目录，核对更新器和测试文件 SHA256，再用独立 venv 重新执行实际测试及静态检查。

| 项目 | 结果 |
|---|---|
| 测试平台 | Linux-6.18.57-x86_64-with-glibc2.41 |
| 测试方法数 | 42 |
| 通过 / 失败 / 错误 / 跳过 | 40 / 0 / 0 / 2 |
| 耗时 | 6.14 秒 |
| 静态检查 | PASS |
| ZIP 内源码与原验收报告哈希比对 | PASS |
| 全量 bundle 独立离线恢复 | PASS |

证据见 `evidence/followup/cloud-recheck.json`、`.log`、`static-security-recheck.json`、`offline-restore.json`、`availability-and-persistence.json`。强杀和退出注入是进程故障测试，**不是断电试验**；模拟交易模块仍为合成模块。

## 尚未通过的必需验收

| 关口 | 验收状态 | 缺少条件 |
|---|---|---|
| Windows 11 异常中断/文件锁/NTFS | 未通过验收（未执行） | 当前仅 Linux；无 Windows 11 测试入口；无 pwsh/powershell、WinRM/远程桌面入口、KVM 设备或 Windows 镜像；Docker 仅 Linux 且无镜像；无已连接桌面文档会话 |
| 真实业务脱敏集成 | 未通过验收（未执行） | 公开账号仅此更新仓库，main 仍仅六文件；缺真实业务模块、脱敏状态 schema、模拟接口合约及夹具 |
| 真实断电一致性 | 未通过验收（未执行） | 无独立 Windows 11 硬件/存储及外部断电控制、重启后持久化证据 |
| 工作区外持久保存 | 未完成 | GitHub 认证失败，且无法从当前工具导出可验证的下载附件 |

Windows 11 测试入口仍为 `Run-Windows11-Acceptance.cmd`。断电夹具为 `powerloss_lab.py` 的 prepare/verify 流程。Linux 复测不能代替这些验收；Windows 目录元数据及磁盘缓存持久化风险仍未消除。

## 获取与恢复方式及限制

- 完整原包及新增自包含 bundle 均在 `v1.4-lab/archives/`；完整本轮交接 ZIP 会另存工作区 `/workspace/work/gang-v14-acceptance-handoff.zip`。
- 若客户端提供工作区文件下载功能，可将此 ZIP 下载到本地，并与外部给出的 SHA256 比对；下载完成之前不能认为已持久保存。
- 指定的 `/codex/.../output` 因只读文件系统无法创建，补充路径写权限后仍失败；没有泛用附件上传/下载导出工具。因此**本次无法承诺提供聊天内可直接点击的有效下载链接**，不会编造外部地址或提供尚不存在的 GitHub 分支链接。
- 认证可用后只推送本地开发分支；成功后须以远程 ref、读取归档文件 SHA256 再确认，不以 `git push` 单条输出替代核验。
- 已取得自包含 bundle 时可离线恢复：`git clone gang-v14-1001f98-full.bundle restored-gang`，再 `git -C restored-gang rev-parse 1001f98`。需要恢复原始 ZIP 直接使用独立归档文件，无需部署。

## 发布结论

**云端合成隔离测试通过，Windows 实机、真实业务集成、真实断电以及工作区外备份均未完成；不符合正式发布标准。** 所有正式系统及真实资金操作保持禁止，必须在验收通过后另获用户批准。没有访问或修改正式 V1.3.2、真实账户密钥、持仓或流水。
