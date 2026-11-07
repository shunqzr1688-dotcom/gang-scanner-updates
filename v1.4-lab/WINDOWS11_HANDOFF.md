# Windows 11 专用实机验收交接

保存前置条件已满足：完整交接包保存于开发分支，固定提交 `8eb2af2740d1cdfede520363aaa92380ec97a588`，远程重新下载和 SHA256 校验通过。原始 `1001f98` 提交历史和全量 Git bundle 也已保存。

## 固定验收输入

- 文件：`gang-v14-acceptance-handoff.zip`
- 大小：340,263 字节
- SHA256：`2d7ea13f4255a6bedfae4c17238c8ab0705191c17c7f781023a20684caa21d48`
- 固定下载 URL：https://raw.githubusercontent.com/shunqzr1688-dotcom/gang-scanner-updates/8eb2af2740d1cdfede520363aaa92380ec97a588/v1.4-lab/archives/gang-v14-acceptance-handoff.zip
- 云端保存回执：`evidence/persistence-receipt.json`

包内历史报告中“未远程保存/认证失败”是快照时间的状态；当前保存状态以本回执为准。包内源代码未改写。不要将历史 Linux PASS 当作 Windows PASS。

## 独立 Windows 11 机器上的准备

仅使用可丢弃的独立 Windows 11 客户端、本地 NTFS、Python >=3.10，PowerShell 按机器既有策略运行。不能与正式 V1.3.2 共用安装目录、数据目录、账户环境或凭证。不要在正式交易机断电。脚本不修改系统 PowerShell 策略，也不要求粘贴 Token。

以下命令只下载、核验并解包验收材料，不部署或启动真实业务；必须在上述独立 Windows 测试机执行：

```powershell
$caseDir = Join-Path $env:TEMP ('GANG-V14-Handoff-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $caseDir -ErrorAction Stop | Out-Null
$zipPath = Join-Path $caseDir 'gang-v14-acceptance-handoff.zip'
Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/shunqzr1688-dotcom/gang-scanner-updates/8eb2af2740d1cdfede520363aaa92380ec97a588/v1.4-lab/archives/gang-v14-acceptance-handoff.zip' -OutFile $zipPath -ErrorAction Stop
if ((Get-Item $zipPath).Length -ne 340263) { throw 'Unexpected archive size' }
if ((Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '2d7ea13f4255a6bedfae4c17238c8ab0705191c17c7f781023a20684caa21d48') { throw 'Archive SHA256 mismatch' }
Expand-Archive -Path $zipPath -DestinationPath (Join-Path $caseDir 'bundle') -ErrorAction Stop
$labDir = Join-Path $caseDir 'bundle\v1.4-lab'
Write-Host ('Verified input ready: ' + $labDir)
```

随后在独立 Windows 11 测试机运行 `$labDir` 中的 `Run-Windows11-Acceptance.cmd`。它只创建临时合成数据和测试子进程。在线模式通过 pip 安装固定依赖，离线模式要求已有 cryptography；具体入口参数见包内 README。Windows Server、Wine、Linux、GitHub 的 Windows Server 托管 runner 均不能充当本次 Windows 11 客户端验收。

## 必须留存的证据

1. OS build 和本地 NTFS 确认、输入 ZIP SHA256；保存 `windows-host.json`、`transcript.txt`、`static-security.json`、`acceptance.json`。
2. Windows 原生文件锁、TerminateProcess、junction、文件占用用例必须执行并通过，不能被平台跳过。Linux symlink 用例在 Windows 有说明性跳过，不替代 Windows junction 用例。
3. 真实业务集成另需脱敏源码、schema、模拟接口和夹具；合成模块 PASS 不能代替真实模块兼容性。
4. 真实断电仅在专用机器、外部控制下进行。`powerloss_lab.py prepare/verify` 的持久化 case 必须放在本地 NTFS 的长期目录，不得存入重启可能清理的 TEMP、临时 VM 磁盘或自动重置目录。可将已验证的 bundle 复制到独立固定实验目录后再 prepare。按 README 的四个关口分别准备新 case，保存外部断电证据与重启后的核验 JSON。
5. OS kill/异常退出/普通重启与真实断电分别记录。任何未执行、跳过或缺少证据的必需关口都标记“未通过验收”，不得推测成功。

## 当前执行状态

本会话仍仅连接 Linux 云环境，没有可用的独立 Windows 11 入口。因此这里只完成了可下载的固定输入、校验和交接准备，**没有执行 Windows 实机或真实断电试验**。本轮未重跑已有 40 项通过的 Linux 测试。main 未修改，未合并、发布或部署。正式部署仍需用户另行批准。
