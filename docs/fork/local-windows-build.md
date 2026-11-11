# Windows 本地测试构建

Windows 可以独立于 GitHub Actions 构建。原生 Windows 继续使用 `desktop-workbench` 中的 `yarn dist:win --x64`；现有发布入口及签名凭据校验保持原样。

## Linux 上已验证的路线

本次在独立目录使用现有脚本编译，再直接调用官方 electron-builder 生成未签名 NSIS 测试包，不修改线上发布资产。

- 使用完整的 Wine 64/32 位组件及新建的 `WINEARCH=win64` 前缀。NSIS 即使安装 x64 应用，也需要运行 32 位卸载器生成程序；此前只有 64 位组件的前缀不能继续复用。
- 从已提交源码准备 Desktop、Connector、Server 版本文件及 logo，复用开发依赖进行编译；桌面界面必须构建自己的 renderer，不能替换成 Web 页面。
- 复用 `cache-native-dependencies.mjs win`、`prepare-uv.mjs` 和 `prepare-python.mjs`，目标均指定为 `win32-x64`，保留原有官方校验值及许可证检查。
- 主进程、界面检查和构建子进程通过现有 `withoutReleaseSecrets` 移除签名凭据。打包阶段使用独立的生产依赖树；本地副本移除 workspace 元数据，让依赖收集器读取正确的生产依赖图。
- 使用现有 electron-builder 配置和 NSIS 模板，显式指定 Electron 版本、官方 Electron 缓存、系统 Wine、`--x64 --publish never`，关闭不需要的依赖重编译及代码签名。已检查的 `win-unpacked` 可通过 `--prepackaged` 重用。
- Desktop 中 Router 原生包的排除规则保持原样：Python Connector 管理 Router，Desktop 只使用 Mesh 客户端，不能为了交叉构建重复引入第二套 Router。

## 本次产物

- 源码：`ceb6dee7`；Windows x64；产品版本仍为 2.5.9，以文件名标识本地测试构建，不触发软件内更新。
- 文件：`Agents Anywhere Fork-2.5.9-local-ceb6dee7-x64.exe`，143,772,390 字节。
- SHA256：`f01bfeb6ed6896f4721d82a291ffa5e9c841c70b9a8b0e4113c656553b781c62`。
- 工具：electron-builder 26.18.1、Electron 39.8.10、Python 3.12.14、uv 0.11.26、系统 Wine 10.0（含 32 位支持）。
- 主进程 158 项、相关界面/队列 24 项检查通过，桌面生产构建通过；NSIS 完整性、产品/版本/服务地址、生产依赖、图标及 Windows x64 二进制检查通过。
- 打包后的 Electron、Python、uv 已作为 Windows 程序在隔离 Wine 环境运行；未执行 Windows 实机安装、真实 AI 任务或 Authenticode 签名。

构建与校验脚本保存在构建机系统盘的独立构建目录中，安装包仅以私有测试下载提供。软件内更新继续使用原公开版本；后续正式更新需明确版本、实机验收及交付记录。
