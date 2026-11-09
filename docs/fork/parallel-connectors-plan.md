# 双 Connector 与用量核查 / 修订方案

用户确认：同一系统账号同时运行官方与 Fork Connector；两版都能执行任务，Fork 使用独立 Codex/Claude 配置目录，允许重新登录。此前 2.5.1 的轮流运行限制在本轮替换。

现状与差异：

1. Electron 安装身份和配置已分离，Python 启动锁仍固定为全用户唯一；改为 Fork 显式隔离配置模式，默认官方锁行为不变。Fork 自己仍只允许一个进程。
2. 只改锁会共享原生账号、历史及 IPC。Fork 的 CODEX_HOME / CLAUDE_CONFIG_DIR 固定为 `~/.agents-anywhere-fork/native/codex` 与 `native/claude`，不读写官方原生配置，禁止指回原目录或用环境覆盖破坏隔离；禁用 Codex Desktop IPC 接管。
3. Fork 安装记录虽已独立，Connector ID 历史仍读官方全局文件；同步切换为 Fork 自己的运行记录，避免误复用官方设备。
4. 用量采集直接执行 PATH 上的 codex/claude，没有沿用正常 Runtime 的 Windows 脚本启动规则，也没有 SDK 自带 CLI 回退；修正为同一套 CLI 选择/启动规则，保留只读方法白名单、白名单脱敏输出与 60/300 秒门禁。
5. 仅在原生工具登录或注册本机设备，不代表已经配置 AA Agent；目前 Server 只从配置过的 Agent 建立采集来源。先让空态说明设备、Agent 和账号三个条件，不伪造额度；配置 Agent 不需要发起收费任务。
6. 提供独立原生登录命令，使用已安装的本机 SDK CLI，浏览器原生 OAuth 由用户完成；不复制凭据、不将账号材料送给 Server 或构建服务。

验证：临时目录证明官方/Fork 可同时持有各自锁、同一模式重复启动仍被拒；官方文件与旧登录目录不变；越界配置/符号链接被拒；Windows 启动 shim 与 SDK 回退、采集白名单/取消回收/门禁回归；两平台原生构建，真机验收由用户完成。测试不启动/停止真实工作 Connector，不采集真实厂商凭据。

客户端内部修复使用 PATCH 2.5.2（Connector/Desktop/renderer/Web）；Server API、RPC 载荷、数据库格式不变。沿用现有服务，不迁移其他服务器的用户和数据。

原生账号存储核对：Codex 的 [认证存储实现](https://github.com/openai/codex/blob/main/codex-rs/login/src/auth/storage.rs) 按 Codex Home 生成 keyring 账户键，文件存储也位于该 Home；Claude 原生登录沿用 [官方 CLI 命令](https://code.claude.com/docs/en/cli-reference)。macOS 私有 keychain 服务选择仍需真实设备验收，不把合成数据测试当作真实账号成功。
