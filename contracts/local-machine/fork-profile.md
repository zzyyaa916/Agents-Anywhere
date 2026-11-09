# Fork 本机隔离约定（2.5.2）

官方 `2.0/README.md` 的默认全用户互斥保持不变。仅显式 `AA_CONNECTOR_PROFILE=fork` 的分叉入口使用本约定；配置、数据目录、启动来源标签均不能单独绕过官方互斥。

- 独立运行记录：系统用户目录 `~/.agents-anywhere-fork/connector-runtime.json`，字段和事务格式沿用 v2，Fork 自己仍单实例。
- Codex Home 固定为 `~/.agents-anywhere-fork/native/codex`；Claude Config 与 SecureStorage Config 固定为 `~/.agents-anywhere-fork/native/claude`。目录链接、junction 与 Agent 环境覆盖被拒绝；原生登录由用户在本机完成，不复制凭据。
- 不迁移官方 Connector ID、安装记录或原生历史；Codex Desktop IPC 接管关闭。
- 官方和 Fork 的会话列表、原生配置及运行记录独立。相同厂商账号的额度仍共享；项目工作目录由用户选择，两个任务若编辑相同文件仍会冲突。
- 不改变 Server API、MeshCall 载荷、数据库或冻结的 v2 记录字段。
