
## 增量条目就位修订（2.7.1）

新条目的 orderSeq 在 int32 范围且会话内未被其他条目占用时按自报值存储，包括迟到的较小序号；否则追加至当前 max+1，溢出则拒绝且不产生写入。已有 ID 始终保持存储位置。同批次抢空位按输入先后顺序，后者追加。完整快照仍需合法序号。beforeOrderSeq 仍是严格小于游标的分页，排序后历史修复会发布 reset fence，客户端需重新读取。

ACP 提交 prompt 时先持久化并上报带 source.clientMessageId 的 user 条目。回声优先用 clientMessageId 关联，无 ID 的 ACP v1 回声仅关联当前明确回合状态，不能按文本去重。
