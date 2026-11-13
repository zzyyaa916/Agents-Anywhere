# 手动项目目录 1.0

`POST /api/v2/projects` 的 `manuallyCreated=true`（默认）表示新建项目：`workspacePath` 是父目录，`name` 是新建的单层目录名。Server 返回的 `project.workspacePath` 是设备创建后的规范化实际子目录。设备须在线；已有同名目录返回冲突，不接管或删除用户原有文件。`manuallyCreated=false` 保留原生/自动导入工作区语义，路径表示已有工作区；不创建目录、不改名或迁移原生会话。

Server 在验证设备所有权和目录名后，以同一账号、设备、目标目录生成稳定的 64 位 SHA256 operationId，在设备生命周期锁内执行：

1. `project.directory.prepare`：`{connectorId, operationId, parentPath, name}` → `{path, receipt}`。设备严格验证目录安全性，只创建不存在的同名子目录，保存路径、设备号/inode 与随机收据。相同 operationId 可重试，但目录身份变化必须拒绝。
2. Server 登记项目，workspacePath 使用设备返回的规范化路径。
3. 成功后 `project.directory.release`：上述请求加 `receipt` → `{released:true}`，仅释放收据。
4. 登记失败时 `project.directory.cancel`：相同载荷 → `{released:true}`，只回收身份和收据匹配的空目录，不能递归删除。回收失败保留目录与收据，绝不能覆盖实际业务失败。

这些调用只在 Server 验证所属账号后下发。RPC 与 JSON KV 不携带原生账号凭据。旧 Connector 未实现 RPC 时明确报错，不降级为“只写项目记录”。稳定父目录别名使用设备规范化路径；最终目录符号链接、敏感路径、主目录、Connector 工作目录及其上级仍不可作为清理对象。

删除计划中的每个 session 可附带 `projectPath`（可空，兼容旧计划），表示真实所属项目目录。会话删除只清理其中 `.agents-anywhere/sessions/<sessionId>` 的专属目录、旧版集中附件与会话缓存、对应原生历史和服务端数据，不删除共用代码。专属目录路径各级拒绝符号链接/junction。项目删除移除绑定项目目录以及该项目所有会话的专属数据，保留父目录和其他项目；原有收据、目录身份与共享路径检查不变。
