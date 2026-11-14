# 项目及会话删除失败排查

## 线上证据

2026-11-14，通过正式 OTP 维护连接，只读查询 ARM Connector 的系统日志。北京时间 15:46:29、15:46:34、15:46:36，history.cleanup.prepare 报 native_history_deletion_unsupported；15:46:46、15:46:47、15:47:05 报 cleanup_shared_project_path。用户确认尝试删除了不同项目及会话，不能将六条记录全部归属「用量分析」，也不能据此断言每次用户点击对应几条请求。

「用量分析」目录仍存在；日志显示这些失败发生在准备阶段，没有继续进入该次请求的删除提交。未重试任何真实删除，也没有解除共享保护。

## 已复现并修复的缺陷

Supervisor 创建 RuntimeInstance 包装器，删除流程也通过 Supervisor 获取该包装器。原生 Codex、Claude、DSH 已有 prepare_history_deletion / delete_session_history，但包装器没有提供这两个方法，导致 HistoryCleanup 误判运行时不支持原生历史删除。

修复在 RuntimeInstance 显式转发两个方法，并保留底层确实不支持时的拒绝行为。不是为未知运行时伪造删除成功。

使用线上 Python 3.12 虚拟环境、干净环境变量及临时目录进行了安装版/修复版对照。安装版报 ValueError: native_history_deletion_unsupported；修复版 Codex、Claude、DSH 三组均确认准备方法和提交方法被转发，并移除了专用临时测试目录。底层原生调用为 AsyncMock，未删除真实聊天历史。复现脚本位于 artifacts/reproduce-history-deletion.py。

## 共享目录保护

cleanup_shared_project_path 表示目标项目目录与其他项目或会话的受保护路径相同、包含或被包含。当前源码明确按这些关系拒绝删除，现有测试也覆盖自路径、子路径及父路径。不能将该错误当作权限问题处理或简单删掉保护。尚未取得服务端各项目/会话的路径清单，不能确定「用量分析」与哪个对象重叠，亦不能认定其为误报。

## 错误提示修复

Server 原本将 RPC 清理失败统一隐藏为「请重试」，Web/Desktop/Android 也会继续用通用错误覆盖服务端提示。现改为对已知的原生历史不支持、共享路径、保护路径及明确权限错误返回有限、可理解的信息，三个客户端显示服务端已归类的清理错误。未知异常仍显示原有提示，不暴露设备路径、凭据或上游正文；错误码和状态码保持原有格式。

## 验证及边界

- 线上安装版/修复版的三运行时隔离对照通过。
- 服务端提示分类和未知错误不泄漏细节的两个单元测试通过。
- 完整 Connector pytest 在本地 Python 3.14 的异步线程等待处停滞；运行时绑定测试另有 ACP 依赖未安装，不能报告该套件通过。
- Android 环境没有 JDK，尚未编译或真机验证。
- 修改只在 /tmp/agents-anywhere-fixes 工作树，未更新或重启线上 Connector/Server/客户端。

最终补充验证：Web 与 Desktop 的 history-delete-dialog.test.mjs 两个回归脚本均通过，新增场景确认已归类的清理错误显示服务端具体原因且确认框保持打开。git diff --check 通过。正式维护连接已关闭。
