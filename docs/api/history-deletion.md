# 历史会话与项目删除 API

分叉 2.3.0，扩展官方 `/api/v2` 资源；删除是不可恢复的历史清理，不删除工作设备上的原生 Agent 历史或工作目录。

- `DELETE /sessions/{session_id}`：204；清理会话、Timeline、shares、planning/goals、上传文件及派生缩略图、待写缓冲和 Runtime 缓存。
- `GET /projects/{project_id}/deletion-preview`：`{projectId, sessionCount, serverTime}`；包括归档和不可见会话，不受列表分页限制。
- `DELETE /projects/{project_id}?expectedSessionCount=N`：在既有响应增加 `deletedSessions`；`detachedSessions` 保持 0。可选期望数量变化时返回 409 `deletion_count_changed`，要求重新确认。
- 对象存在但非本人所有：403；不存在/重复删除：404。运行、排队、停止中、待批准、active run、未结束创建工作流、活动目标/未完成目标操作：409 `session_running`，detail 包含 `sessionIds`。请先停止。
- 文件或缓存清理失败返回 503 `deletion_cleanup_failed`，不可视为成功；请求可重试。SQL 与文件没有共同事务：SQL 回滚可保留原对象，但已删除的文件不能回滚。故障期间请重试删除，不能继续使用缺失附件。

Server 以数据库事务检查所有权和忙碌状态，项目全部子会话检查成功才删除；上传共享会话行锁与删除排他锁隔离。原生来源重放由删除标记拦截：只保留对象 ID、操作者、UTC 时间和原生身份 SHA-256，不保留正文、路径或凭据。操作审计记录对象 ID、操作者、时间、数量。统计报表为既有平台活动事实，保留聚合口径。

Web 与 Desktop 两套 renderer 都使用同一 API 语义，确认框可取消，项目需输入项目名并展示服务端精确数量；成功立即移除列表。官方移动端不新增 UI，刷新现有列表即可反映 Server 删除结果。
