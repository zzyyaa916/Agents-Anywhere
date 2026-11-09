# 2.5.1 并排安装交付记录

> 本文记录 2.5.1；双 Connector 同时执行任务请使用 [2.5.2](../releases/2.5.2-fork-desktop.md)，并重新登录隔离原生账号。

## 目标与边界

同一台 Windows 电脑、同一个系统账号安装官方版和 Fork；不需要虚拟机。安装、登录回调和应用配置分离；Connector 保留全局互斥，轮流使用。原生 Codex / Claude 账号、历史与用户工作区仍共享，并非两套运行沙箱。

本次是在既有删除、用量和限额续聊功能之上修复客户端安装冲突；未改变说明书 §4.2 的数据来源、§4.3 的采集门禁或 §2 的凭据边界。

## 文件与要求

| 文件 | 对应要求 |
| --- | --- |
| `desktop-workbench/package.json`、`electron/main.ts` | 产品名 Agents Anywhere Fork、独立 appId，区分 Windows 安装/卸载项、快捷方式、macOS 应用和 Electron 用户数据。 |
| `desktop-workbench/config.json` | 独立浏览器协议和 OAuth clientId，防止两版互相接收登录。 |
| `desktop-workbench/electron/machine-state.ts`、`electron/backend/state.ts` | Fork 安装记录、引导状态存入独立文件；只读全局 Connector ID 历史，保留全局互斥，不强行终止旧进程。 |
| `desktop-workbench/electron/desktop-oauth.test.ts`、`desktop-onboarding.test.ts`、`machine-state.test.ts` | 独立身份、旧协议拒绝、状态不改写官方记录回归。 |
| `desktop-workbench/electron/desktop-onboarding.ts` | 文档示例同步新协议。 |
| `desktop-workbench/scripts/dist-desktop.mjs` | 签名验证按实际产品名寻找 Mac 应用。 |
| `server/agent_server/core/oauth_clients.py`、`web-next/src/features/auth/native-oauth.ts` | 新增严格匹配的 Fork 登录客户端，保留官方客户端，拒绝回调混用和附加参数。 |
| `server/tests/test_fork_desktop_oauth.py`、`server/tests/test_auth.py`、`web-next/test/onboarding-flow.test.mjs` | 两版回调边界与完整 PKCE 授权码流程。 |
| Server pyproject/app、Desktop/renderer、Web package/demo 元数据 | 同步相关端 2.5.1；无字段、事件、端点或数据库 schema 变动，Connector 仍为 2.5.0。 |
| `.github/workflows/fork-desktop-build.yml`、`desktop-workbench/scripts/cache-native-dependencies.mjs`、`prepare-uv.mjs`、`prepare-python.mjs` | 官方 Release API 缓存同版本依赖，原打包器继续验证 uv/Python，并额外验证 Electron SHA256；仅导出原有版本常量，省去重复下载，打包最多三轮，不放松检查。 |
| CHANGELOG、2.5.1 发布说明、旧安装包交付记录、本文 | 用户安装、切换、回退和验收边界。 |

## 验收

- [x] 本地 Desktop 主进程 165/165 通过。
- [x] 本地 Web 476/476 通过；Web/Desktop renderer 类型和协议检查通过。
- [x] Server OAuth 严格匹配与架构边界 3 项通过；既有 OAuth 相关 9 项通过；两版桌面 PKCE 端到端 2 项通过。
- [x] 临时目录中的真实 Electron 进程确认 Fork 用户数据路径使用独立应用名称，不启动 Connector。
- [x] Fork 安装与引导状态写入后，官方全局记录字节不变。
- [x] Fork Server/Web 2.5.1 已更新，公网 9443 返回 200；官方 443 仍为 2.1.0、容器 ID/镜像/启动时间不变。
- [x] 更新前在服务器本机备份 Fork 数据库；未迁移或重新初始化用户、密码和业务数据，注册仍关闭。
- [x] 回退镜像和更新前配置保留；不修改 Nginx 或系统网络，不停止本机工作 Connector。
- [x] 本轮临时 SSH 公钥撤销，新连接被拒绝；本地临时私钥删除，其他 SSH 公钥保留。
- [x] 最终原生 Windows CI：165 项中 153 通过、12 跳过、0 失败；macOS：164 通过、1 跳过、0 失败。因避免重复下载，最终 CI 未安装 node_modules 下的 Electron，仅跳过一项真实 Electron 非 ASCII 路径用例；此前同产品代码在 Windows（154 通过、11 跳过）和 macOS（165 通过、0 跳过）已实际执行该用例并通过。
- [x] 两平台 renderer 类型与协议检查、原生官方打包脚本均通过；下载两份产物与 CI SHA256 清单完全一致，Windows PE 与 Mac DMG 格式验证通过。
- [ ] 用户 Windows 真机安装、两版托盘切换、浏览器唤起和原生 Runtime 实测仍待用户验收。

## 部署与回退

更新源码 `4c8d3f2f`；镜像 `agents-anywhere-fork:2.5.1-4c8d3f2f`，镜像 ID `93603197aa1c`。本轮更新只替换干净 Server 和 Web 静态文件，沿用原镜像中已验证的依赖；不重新解析或下载依赖。数据库保持 `v2_56`。

服务器备份 `backups/before-2.5.1-20261109T073025Z.dump`（0600）和同时间戳配置备份。回退只恢复 Fork 的原 `FORK_IMAGE` 后执行 `docker compose --env-file fork.env -f compose.yml up -d --no-deps server`；无数据库降级。完整停用仍可用原 `disable-fork.sh`，保留卷。

## 当前 2.5.1 并排安装包

- [Windows x64 ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42581972039/artifacts/13657309502)
- [macOS universal ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42581972039/artifacts/13658130916)
- [成功原生构建](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42581972039)；源码 `c536513263a418b12acf6fbed4887f94247831dd`。

无需虚拟机或第二个系统账号，保留默认 Fork 安装目录即可；两版 Connector 须轮流运行。ZIP 内含安装文件和 SHA256SUMS，GitHub 登录后下载，保存 14 天。[完整验收与文件列表](side-by-side-desktop-delivery.md)。

| 文件 | 字节数 | SHA256 |
| --- | --- | --- |
| `Agents Anywhere Fork Setup 2.5.1.exe` | 311176620 | `f4a6f82cedfb42f95004072c7298f1c6bcb620f0ae93ec4dceaef4b12437a29b` |
| `Agents Anywhere Fork-2.5.1-universal.dmg` | 542766028 | `1a3168b4a614c7458bb07238317a489c96b1f1e85fcb5ac5ca4d4cf266c21687` |

## 安装与风险

请保留新包默认独立安装目录，不要选择官方版目录；旧 2.5.0 测试包已标明不能在同一系统账号覆盖安装。选择自托管地址 `https://81.71.71.114:9443`，用现有管理员账号登录，不需要注册。

测试前结束官方版任务并从托盘退出，再启动 Fork；返回时反向操作。不可同时启动两个本机 Connector。新包未签名，macOS 未公证。未使用或上传真实厂商凭据，构建与单元检查不代表真实额度和续聊效果已验收。
