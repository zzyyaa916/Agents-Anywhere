# 2.5.2 双 Connector 交付记录

## 需求与文件

用户确认同一系统用户下官方和 Fork 均可执行任务，Fork 独立 Codex / Claude 配置并重新登录；不迁移其他服务器，不开发 iOS。核查与修订方案见 [parallel-connectors-plan.md](parallel-connectors-plan.md)。遵循 ponytail：沿用原有锁、SDK 选择、CLI 启动与用量采集流程，未增加依赖或 Server 端点。

| 文件 | 对应需求 |
| --- | --- |
| `connector/connector/core/fork_profile.py`、`core/runtime_owner.py` | 显式 Fork 配置、独立运行锁和 ID 历史，不迁移官方记录；凭据红线 §2。 |
| `connector/connector/runtimes/codex/provider.py`、`codex/provider_config.py`、`claude/provider_config.py` | 保护原生目录和环境，关闭 Fork Codex Desktop IPC 接管；双版可执行任务。 |
| `connector/connector/native_cli.py`、`native_login.py`、`cli.py` | SDK CLI 回退、Windows shim 兼容、独立本机原生登录；凭据不写入 AA 日志、不复制到另一设备。 |
| `connector/connector/account_usage.py` | 复用原生 CLI 选择与隔离目录，macOS Claude 私有 keychain 服务定位；保留 §4.2 数据来源、§4.3 门禁与脱敏。 |
| `desktop-workbench/electron/connector-supervisor.ts`、`local-runtime.ts` | Desktop 为自己的 Connector 设置独立运行记录和原生目录。 |
| `desktop-workbench/electron/native-login-launchers.ts`、`main.ts` | Windows 托盘与 macOS 应用菜单原生登录入口，以及数据目录中的本机启动文件。 |
| `connector/tests/test_fork_profile.py`、`test_account_usage.py` | 独立锁、真实双进程、重复进程拒绝、禁止覆盖/链接、无凭据复制、登录无日志捕获、Windows shim 与 IPC 升级回归。 |
| `desktop-workbench/electron/{connector-supervisor,local-runtime,machine-state,main-lifecycle,native-login-launchers}.test.ts` | 环境、ID、官方文件不变、菜单调用、中文/空格/引号/百分号路径与终端脚本回归。 |
| `web-next/src/components/account-usage.tsx`、`desktop-workbench/renderer/src/components/account-usage.tsx` 及两端 `test/account-usage.test.mjs` | 圆圈弹窗保留，缺设备/Agent/原生登录时给出下一步；不要求先发起任务。 |
| Connector pyproject、Desktop/renderer/Web package、Web demo 元数据 | 客户端 2.5.2；Server 留在兼容的 2.5.1，无数据库或协议字段变化。 |
| `contracts/local-machine/fork-profile.md`、CHANGELOG、2.5.2 发布说明、方案及本文 | 隔离约定、升级操作和验收边界；冻结契约不改写。 |

## 验收清单

- [x] Connector 相关测试 121 通过、1 跳过（Darwin 路径语义专用例，本地为 Linux）。
- [x] 两个真实临时 Python 进程同时保有官方/Fork 租约，两种模式各自的第二实例均返回拒绝；不连接真实后端。
- [x] 合成官方凭据不读取或复制，官方运行文件字节不变；不采集真实账号来测试。
- [x] 原生目录覆盖、符号链接被拒；旧 IPC 开启配置升级后归一化为关闭。
- [x] 新登录子进程只使用私有目录，API 认证环境不转交给订阅账号登录，不捕获 stdout/stderr；登录码仅在本机原生终端显示。
- [x] 本地 Desktop 主进程 166/166 通过；Web 与 Desktop 用量弹窗交互测试各 1 项通过。
- [x] Web / renderer 类型检查与 Desktop renderer 协议检查通过；修改的 Python 文件 lint 通过。既有 runtime_owner 的 TRY004 历史问题未顺手改动。
- [x] 保留 Codex 只读 RPC 方法白名单、Claude 用量来源、白名单输出、60/300 秒间隔和既有 429 退避；既有采集回归通过。
- [x] Windows 原生构建：166 项中 154 通过、12 跳过、0 失败；renderer 类型/协议与原生打包通过，下载后 SHA 和 PE 格式核对通过。
- [x] macOS 原生构建：166 项中 165 通过、1 跳过、0 失败；renderer 类型/协议与 universal 打包通过，下载后 SHA 和 DMG 格式核对通过。两平台各有一项真实 Electron 探针因 CI 跳过 Electron postinstall 下载而跳过，仍需真机验收。
- [ ] 用户真机双开、厂商 OAuth、真实额度、两版各自执行任务及新隔离会话续聊：需用户设备验收。

## 升级与风险

按 [2.5.2 发布说明](../releases/2.5.2-fork-desktop.md) 操作；原生账号需重新登录，不复制官方历史。旧 AA 会话列表保留，但引用官方原生历史的旧线程不保证能在新目录恢复；请新建测试会话。两个进程沿用同一系统用户的文件权限；双版若编辑同一项目文件仍可能冲突，使用不同测试目录。厂商同账号额度共享。Windows 未签名，Mac 未公证。

本轮不部署 Server/Web：现有 2.5.1 API 可接收新版 Connector 的脱敏用量；Web 源码的新说明在后续部署时生效。未请求 SSH、未调整网络、未停止任何真实工作 Connector。

## 安装包

生产代码提交 `b5604ee3f5ab8e7ba57b59d4dc18e100ea6c419d`；之后仅补测试与文档，不改变安装包生产代码。
原生构建：[42593013015](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42593013015)。

- [Windows x64 ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42593013015/artifacts/13662333361)，内含 `Agents Anywhere Fork Setup 2.5.2.exe`，311187612 字节。
- Windows SHA256：`679fb24f76485fbb94c8f1cc34129d41c2c6f96b2a2fab4d3f864615277f6b12`。
- [macOS universal ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42593013015/artifacts/13663530002)，内含 `Agents Anywhere Fork-2.5.2-universal.dmg`，542817538 字节。
- macOS SHA256：`413cfc404236b622f06f51bbce8d59e928120e210d46c9368b10d49fc50f4832`。

Actions 产物保留 14 天，下载需登录 GitHub。
