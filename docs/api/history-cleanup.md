# 完整删除协议

API namespace 为 `/api/v2`，所有请求必须登录且拥有目标对象。

- `DELETE /sessions/{sessionId}/contents`：成功返回 204。
- `GET /projects/{projectId}/deletion-preview`：返回 `projectId`、`sessionCount`、`serverTime`。
- `DELETE /projects/{projectId}/contents?expectedSessionCount=N`：返回标准 ProjectDeleteResponse；预览人数改变时返回 409。

403 表示无权限，404 表示对象不存在，409 表示忙碌、共享历史或预览已改变，503 表示工作设备清理尚未完成，可重试。旧的不带 `/contents` 的 DELETE 保持仅删除服务端记录的兼容语义。

## Connector RPC

`history.cleanup.prepare` 参数为 `{operationId, connectorId, projectPath, protectedPaths, sessions}`。operationId 为 32 位小写十六进制；projectPath 为空或绝对路径；protectedPaths 为其他项目和会话的路径列表；sessions 每项含 sessionId、runtimeId、runtime、externalSessionId、cwd，可附带其所属项目的 projectPath。Connector 验证设备身份、原生历史可删除性、目录归属及权限，记录路径的设备号/文件号和请求摘要，返回 `{prepared:true,receipt}`，不删除文件。

Server 在记录删除的同一事务内将 `{request,receipt}` 保存到 history_deletion_audit.device_cleanup_json，然后调用 `history.cleanup.commit`，参数为该保存对象。Connector 核对完整摘要、随机凭据、目录身份，再删除原生历史、缓存和确认的目录；返回 `{complete:true}`。重复提交已完成操作只返回成功，不会删除后来新建的目录。失败保留任务并在恢复时重试；任务完成后 Server 清除计划正文。

无法确认可删除的 Runtime、共享原生身份、未知 DSH 存储格式及固定身份旧 Broker 均拒绝操作，不能退回“只删记录”并返回成功。

## 失败与放弃

`POST /projects/{id}/contents/abandon` 与 `POST /sessions/{id}/contents/abandon`：本人确认放弃尚未完成的设备清理，成功返回 204。不会恢复已删除的数据，尚未清理的设备文件和原生历史保留。必须先让在线设备确认 `history.cleanup.cancel`，以阻止迟到的 commit；再解除项目路径占用并完成服务端清理。设备离线时返回 503，仍保留路径保护。Android、Web、Desktop 的失败删除对话框和 iOS 项目删除恢复入口提供二次确认。

`history.cleanup.cancel` 使用原 `{request,receipt}`，与 commit 共用设备锁，取消后删掉凭据，迟到的 commit 会因缺少凭据被拒绝。事务明确拒绝删除时也发送 cancel，避免残留预检记录。

设备 commit 成功后，Server 先持久化 `deviceComplete:true`，再发送 `history.cleanup.release` 释放设备凭据，最后完成审计。release 或其确认丢失可重复执行，重试不再执行原生删除。未确认取消的凭据不会擅自过期，以免改变正在恢复的删除任务。

只将 Connector RPC 失败、超时和明确的设备未确认状态映射到设备清理 503；未预期的数据库、程序和服务端存储错误沿用 500 错误处理。

项目父目录的稳定符号链接可被解析为真实目录；最终待删目录本身的符号链接或 junction 仍拒绝。后续清理使用预检记录的真实路径，并在删除前再次核对目录身份。Windows 大小写、短路径和文件占用仍需实机验收。

项目目录内的 `.agents-anywhere/sessions/<sessionId>`（如存在）属于该会话专属数据；清理只删除匹配会话目录，保留共用代码及其他会话缓存，各级符号链接和 junction 会被拒绝。项目创建与收据协议见[项目目录 1.0](../../contracts/project-directory/1.0/README.md)。
