# Windows / macOS 测试安装包交付（2026-11-09）

## 当前 2.5.1 并排安装包

- [Windows x64 ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42581972039/artifacts/13657309502)
- [macOS universal ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42581972039/artifacts/13658130916)
- [成功原生构建](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42581972039)；源码 `c536513263a418b12acf6fbed4887f94247831dd`。

无需虚拟机或第二个系统账号，保留默认 Fork 安装目录即可；两版 Connector 须轮流运行。ZIP 内含安装文件和 SHA256SUMS，GitHub 登录后下载，保存 14 天。[完整验收与文件列表](side-by-side-desktop-delivery.md)。

| 文件 | 字节数 | SHA256 |
| --- | --- | --- |
| `Agents Anywhere Fork Setup 2.5.1.exe` | 311176620 | `f4a6f82cedfb42f95004072c7298f1c6bcb620f0ae93ec4dceaef4b12437a29b` |
| `Agents Anywhere Fork-2.5.1-universal.dmg` | 542766028 | `1a3168b4a614c7458bb07238317a489c96b1f1e85fcb5ac5ca4d4cf266c21687` |

> 以下是旧 2.5.0 包，沿用官方安装标识，不要覆盖安装。适合同一系统账号并排安装的新包说明见 [2.5.1](../releases/2.5.1-fork-desktop.md)。

## 下载

- [Windows x64 ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42574403306/artifacts/13654512523)
- [macOS universal ZIP](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42574403306/artifacts/13655112140)
- [成功的原生构建任务](https://github.com/zzyyaa916/Agents-Anywhere/actions/runs/42574403306)
- [用户分叉仓库](https://github.com/zzyyaa916/Agents-Anywhere/tree/fork-desktop-test)

GitHub 下载需要登录；本次 Actions 产物保留 14 天，每个 ZIP 含安装包和 CI 生成的 `SHA256SUMS.txt`。产物来自提交 `21bb76e92fb47deeda21595c9de0490d63ae46f5`，项目版本 2.5.0；说明文档的后续提交不会改写该产物。

| 平台 | 安装文件 | 字节数 | SHA256 |
| --- | --- | --- | --- |
| Windows x64 | `Agents Anywhere Setup 2.5.0.exe` | 311093590 | `b67d8d45bfe35829065e0f5a48a7eab853129a575e453675f6c029e7168fa894` |
| macOS universal | `Agents Anywhere-2.5.0-universal.dmg` | 542690514 | `46cc779498ba94421682895538ce47e322fa930bc087624da468a59fbbc10e66` |

## 改动文件及对应要求

| 文件 | 目的 |
| --- | --- |
| `web-next/package.json`、`desktop-workbench/renderer/package.json` | 修正此前升级项目版本时误改的 `@noble/hashes`；恢复官方已发布的 2.4.0，项目自身仍为 2.5.0。对应说明书 §7 的可实际构建交付。 |
| `.github/workflows/fork-desktop-build.yml` | GitHub 已拒绝旧 `macos-14` runner，改用 `macos-latest`；保留 Windows x64 / macOS universal 和官方原生打包脚本。 |
| `.gitattributes` | 契约和生成的协议 TypeScript 固定 LF，避免 Windows CRLF 检出导致哈希及内容校验失败；不修改契约字节或放宽校验。 |
| 本文、Ponytail 核查、生产部署记录、2.5.0 发布说明、CHANGELOG | 同步实际安装包状态、下载及验收边界。 |

二进制、本机 GitHub 授权配置、构建日志和下载缓存均不提交。未读取任何真实 Codex / Claude 登录凭据，也没有向 GitHub 提供厂商凭据。签名凭据没有配置。

## 验收结果

- [x] 用户网页登录授权后创建独立 fork，推送分叉分支；官方仓库未写入。
- [x] GitHub 原生 Windows 和 macOS 构建均成功，来源为同一提交。
- [x] Windows 主进程测试：163 项中 152 通过、11 跳过、0 失败；macOS：163 通过、0 跳过、0 失败。
- [x] 两平台 renderer 类型与协议检查通过，官方 `dist:win --x64` / `dist:mac --universal` 打包成功。
- [x] 本地 Windows 式 CRLF 检出模拟中，91 项契约哈希通过，生成文件保持 LF。
- [x] 本地两端密码校验专项各 7 项通过。
- [x] 下载两份真实安装包，与 CI 的 SHA256 清单逐一匹配。
- [x] Windows PE 文件头有效，未包含 Authenticode 签名；macOS DMG 的 UDIF 尾部格式标志有效。
- [ ] Windows 真实安装/启动、macOS Gatekeeper 与真实安装尚待用户验收。
- [ ] 真实厂商额度对照、多设备账号聚合、限额后上下文续接继续按原功能验收清单实测，不能用构建成功代替。

## 安装与隔离限制

这批包沿用官方应用标识、应用名、OAuth 协议和 Connector 单用户互斥锁，**不能宣称与同一系统用户下的官方版完全隔离**。请使用虚拟机或独立系统用户测试：Windows 选择仅当前用户安装，避免覆盖官方目录；macOS 安装到该测试用户的 `~/Applications`，不要覆盖系统 `/Applications` 中的官方版。单独建 Python venv 或只换安装目录不等于系统用户隔离，不要接管仍在运行的官方 Connector。

ZIP 解压后运行 `.exe` 或打开 `.dmg`，选择自托管服务器 `https://81.71.71.114:9443`。管理员为 `admin@agents.local`，密码沿用隔离部署时官方服务器的管理员密码；之后两版密码修改互不联动。厂商账号须在测试工作设备本机登录，不能发送 token / API key 到聊天或 Server。未接入真实账号时显示用量不可用，不是固定 12% 的演示数据。

两份包均为未签名测试包，macOS 也未公证，可能遇到系统安装/启动提示。官方服务器仍在原地址，独立服务的停用方式见[隔离部署说明](isolated-deployment.md)。
