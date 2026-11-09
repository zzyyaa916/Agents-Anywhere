# 平台协议 1.2

增加会话 `limited` 状态及 `quotaLimit`，见 ../../session-quota/1.0/README.md。1.0 与 1.1 原始契约保持不变，导出器为旧版本投影既有枚举/字段。新 Web / Desktop 从 v1_2 生成类型，Server 继续接受旧版本协议请求。官方移动客户端可能将 limited 映射为 unknown；到点后 Server 所有列表/状态/发送路径投影 idle，真实官方 App 降级续聊仍须实测。
