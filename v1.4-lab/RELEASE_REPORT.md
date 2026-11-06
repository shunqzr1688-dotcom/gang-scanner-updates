# GANG V1.4 发布准备报告

日期：2026-11-07（Asia/Shanghai）。结论：**云端隔离开发及测试完成；不批准正式上线，不作 Windows 或断电通过声明。**

## 来源及范围

- 来源： https://github.com/shunqzr1688-dotcom/gang-scanner-updates
- 基线 main：`7046750f604df1b6a8f3a86666564b37981acd5f`
- 本地开发分支：`dev/v14-release-prep`。未推送远程、未修改 main、未发布 Release 或部署。
- 变更限定于本地实验更新器、合成测试、验收程序、文档与证据；新增 `.gitignore` 排除缓存和测试输出。
- 未停止或修改正式 V1.3.2，未访问真实账户、资金、交易记录或持仓。根目录 manifest 保持 1.3.2/no_update。

## 已实现与修复

1. 修复原入口的缩进错误，改为转入单一维护的事务实现。
2. 离线安装：固定信任公钥 Ed25519 签名、严格 JSON/schema、递增三段版本防降级/重放。
3. 完整包：要求四个固定模块，整包和逐文件 SHA256；拒绝缺文件、重复路径、路径穿越、链接、加密条目、超限压缩内容。
4. 隔离保护：专用 marker 内容、test_mode、root id，拒绝根及父目录链接、Windows reparse/junction、受管文件硬链接和不安全备份目录。
5. Linux flock / Windows msvcrt 原生文件锁，锁文件保持同一 inode；进程被强杀后由 OS 释放锁。
6. 事务日志 PREPARED → APPLYING → COMMITTED，故障后 ROLLED_BACK；在改写前生成并校验完整备份。日志保留旧/新各文件的哈希，受管配置也参与事务。
7. 恢复前先校验所有备份，遇损坏拒绝恢复；恢复中再次崩溃可重入。提交后的集合损坏会报错，不报告成功。
8. 文件 flush/fsync、唯一临时文件和 atomic replace；POSIX 目录 fsync。Windows 目录元数据持久化未获保证。
9. 包内模块进行语法及保守 AST 检查；更新器不联网、不执行下载候选代码、不启动真实扫描器。
10. 生成 Windows 11 本地 NTFS 一键验收程序、持久化断电前后核验夹具及说明。

## 实际执行结果

最终权威运行在新建 `/workspace/work/gang-v14-testenv` venv 中执行，依赖由固定版本要求全新安装，`pip check` 通过；环境元数据见 `evidence/isolated-environment.json`。最终权威运行见 `evidence/linux-acceptance.json` 与 `.log`；其他早期开发运行不作为发布验收证据。

| 项目 | 结果 |
|---|---|
| 平台 | Linux 6.18.57 x86_64 / glibc 2.41 |
| Python / cryptography | 3.12.14 / 50.0.0 |
| 最终测试方法数 | 42 |
| 通过 / 失败 / 错误 / 跳过 | **40 / 0 / 0 / 2** |
| 运行时间 | 约 7.19 秒 |
| 新静态结构检查 | PASS，见 static-security.json |
| 原独立检查 | 6 PASS，0 FAIL，1 WARN，7 REVIEW，2 SKIP；不是行为验收 |
| Windows 专属 junction / 文件占用 | 跳过；需要 Windows |
| Windows 断电准备脚本在 Linux 的防误用检查 | 如预期退出 1，提示必须使用 Windows 11 |
| Windows PowerShell / CMD 程序实际执行 | 未执行，本环境没有 Windows/PowerShell |
| 真实断电 / Windows 实机验收 | 未执行 |

哈希绑定：

- 最终更新器 SHA256：`b708a73604e590b0de1b7faadaec9d8ea7ba493859425a12766d77ff714711da`
- 最终行为测试 SHA256：`3da68a310321617232620536a4ad6d245cd5744e808cda9cacf67d42cdc4dc8b`

已运行的行为覆盖包括：完整安装、dry-run、禁用、签名/固定公钥失败、整包/逐文件篡改、版本重放、严格 schema、重复 JSON key、缺模块、ZIP 穿越/重复/符号链接/解压大小上限、候选危险代码拒绝、marker/scanner guard、硬链接/父目录链接拒绝、备份阶段磁盘失败、提交日志写失败、atomic replace 权限失败、恢复阶段写失败后重试、备份损坏前置拒绝、日志损坏/路径穿越/空哈希拒绝、提交集损坏检测、缺失原文件恢复删除、交易状态完整性。

故障注入明确包括：

- `os._exit(91)` 覆盖备份就绪、PREPARED、APPLYING、四模块及配置各次写入、提交前和提交后。
- 真正 `Popen.kill()` / Linux SIGKILL 覆盖 PREPARED、首模块、配置已写、COMMITTED；随后用独立新进程恢复并核验锁释放。
- 文件 fsync 后但 replace 前的崩溃，包括模块、配置、事务日志。
- 恢复各次写入中再次 `os._exit`，最后重试恢复旧完整集合。
- 两个独立安装进程串行互斥；第一个被强杀后第二个自动恢复再安装。

测试正常拒绝的错误及注入异常均为**预期通过路径**，没有遗留的意外测试失败。Windows 跳过和硬件未验收仍是阻断条件。

模拟交易用 Decimal 执行买卖、资金不足、持仓不足、非法订单，验证合成现金/持仓/流水数据与更新前后哈希。只执行测试内生成且逐字核对的固定 mock 模块，未执行仓库外业务代码。该结果**不能证明真实业务兼容性**。

旧独立检查的 WARN 是其文本检查找不到 `resolve` 字样；新实现采用逐级 lstat/reparse/hardlink 检查，行为测试覆盖对应路径。这不作为真实 Windows 路径安全的替代证据。

## Windows 交付和复测入口

- 双击 `Run-Windows11-Acceptance.cmd`，仅在专用 Windows 11 本地 NTFS 机器使用。
- 程序新建 venv/temp，记录 OS build、完整 transcript、静态检查和逐项 JSON；在线模式安装固定 cryptography 50.0.0，离线模式使用显式 Python 的现有依赖。
- `powerloss_lab.py prepare` 生成持久化合成状态并暂停自己的 child；由专用测试机外部执行真实断电后，`verify` 恢复与核对。脚本不会关机/重启。操作员声明与自动证据分别记录。
- 具体命令、四个断电关口、证据留存和边界详见 README。

## 剩余风险 / 缺失条件

1. 没有可用 Windows 11 测试入口；原生锁、NTFS replace/占用、junction、防病毒/ACL 行为和 PowerShell 程序尚未实跑。
2. 没有真实断电证据。Windows 缺少此实现可移植的目录 fsync，磁盘缓存/硬件写屏障是否保证持久化未知；不得宣传断电安全。
3. 缺真实业务模块、脱敏真实 schema、模拟账户 API 合约和集成夹具；目前只是合成业务兼容测试。
4. 这是实验室离线更新器，尚无真实扫描器生命周期握手、生产读者排他协议、线上分发/下载、正式信任链/密钥轮换或服务调度。新签名清单和完整包规则与旧入口不兼容，必须单独做集成迁移。
5. AST 策略不是 Python 沙箱，也不证明恶意代码安全；实际业务导入可能被拒绝。更新器不执行候选，但日后运行真实业务需要单独审计。
6. 日志与备份哈希处理偶发损坏，不防可改写整个私有实验目录的同权限攻击者。并发恶意路径替换不在当前模型内；只支持私有目录和本地文件系统。
7. 失败可留下备份或唯一临时文件，保留审计证据；尚无自动清理策略。存储不可写、备份损坏时会阻断并保留现场，需修复介质再恢复。
8. 指定 `/codex/.../output` 在本运行环境不可创建（只读文件系统）。完整源码、补丁、压缩包和报告保存在 `/workspace/work`，本限制与测试结果无关。

## 发布结论

**可以进入专用 Windows 11 隔离验收；不可正式上线。** 必须依次补齐 Windows 原生测试、外部断电与存储持久化证据、真实业务模块的脱敏模拟集成，以及生产生命周期/分发/密钥方案审查。通过后仍需用户明确批准正式部署或任何真实资金操作。本次未部署，也未向远程仓库写入。
