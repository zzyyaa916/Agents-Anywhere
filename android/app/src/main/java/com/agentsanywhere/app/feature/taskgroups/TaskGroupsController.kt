package com.agentsanywhere.app.feature.taskgroups

import com.agentsanywhere.app.api.TaskGroupsApi
import com.agentsanywhere.app.api.TaskGroup
import com.agentsanywhere.app.feature.auth.AuthSessionReader
import com.agentsanywhere.app.feature.sessions.*
import com.agentsanywhere.app.feature.devices.DeviceRuntime
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

class TaskGroupsController(private val api: TaskGroupsApi, private val auth: AuthSessionReader) {
    private suspend fun <T> request(action: (String, String) -> T): Result<T> = withContext(Dispatchers.IO) {
        try {
            val server = auth.readServerUrl()
            val token = auth.readAccessToken()
            check(server.isNotBlank() && token.isNotBlank()) { "请先登录" }
            Result.success(action(server, token))
        } catch (error: CancellationException) { throw error }
        catch (error: Exception) { Result.failure(error) }
    }
    suspend fun list(project: String) = request { s, t -> api.list(s, t, project) }
    suspend fun restore(project: String, root: String?): Result<List<TaskGroup>> {
        val groups = list(project).getOrElse { return Result.failure(it) }.associateBy { it.id }.toMutableMap()
        var next = root
        val seen = mutableSetOf<String>()
        while (next != null && seen.add(next)) {
            val group = groups[next] ?: get(next).getOrElse { return Result.failure(it) }.also { groups[it.id] = it }
            next = group.sourceId
        }
        return Result.success(groups.values.toList())
    }
    suspend fun get(id: String) = request { s, t -> api.get(s, t, id) }
    suspend fun start(id: String, slot: Int) = request { s, t -> api.start(s, t, id, slot) }
    suspend fun create(operation: String, project: String, text: String, configs: List<NewSessionRuntimeSelectionState>, attachments: List<NewSessionAttachmentPart>) = request { s, t ->
        require(text.isNotBlank() && text.length <= 32000) { "任务文字须为 1–32000 字符" }
        require(configs.size in 1..3 && configs.all { it.readyForCreate }) { "请选择 1–3 个已就绪的 AI" }
        require(attachments.size <= 10 && attachments.all { it.bytes.isNotEmpty() && it.bytes.size <= 25 * 1024 * 1024 }) { "最多 10 个附件，每个不超过 25 MB 且不能为空" }
        require(attachments.isEmpty() || configs.all { it.canUseAttachments }) { "所选 AI 不支持附件" }
        api.create(s, t, JSONObject().put("operationId", operation).put("projectId", project).put("content", text)
            .put("candidates", JSONArray(configs.map(::targetJson)))
            .put("attachments", JSONArray(attachments.map { part -> part.toInlineAttachmentRef().let { ref ->
                JSONObject().put("fileId", ref.fileId).put("name", ref.name).put("mediaType", ref.mediaType)
                    .put("size", ref.size).put("sha256", ref.sha256).put("contentBase64", ref.contentBase64)
            } })))
    }
    suspend fun handoff(operation: String, group: String, slot: Int, config: NewSessionRuntimeSelectionState, instructions: String, fileIds: List<String>) = request { s, t ->
        require(config.readyForCreate) { "目标 AI 尚未就绪" }
        require(instructions.isNotBlank() && instructions.length <= 8000) { "转发指令须为 1–8000 字符" }
        api.handoff(s, t, group, JSONObject().put("operationId", operation).put("slot", slot).put("mode", "continue")
            .put("target", targetJson(config)).put("instructions", instructions)
            .put("attachments", JSONArray(fileIds.distinct().map { JSONObject().put("fileId", it) })))
    }
}

private fun targetJson(config: NewSessionRuntimeSelectionState): JSONObject = JSONObject()
    .put("runtime", requireNotNull(config.selectedRuntime).type).put("runtimeId", config.selectedRuntimeId)
    .put("selections", JSONObject(config.selections.toMap()))

data class ForwardCommand(val runtimeId: String, val instructions: String)
fun parseForwardCommand(text: String, runtimes: List<DeviceRuntime>): ForwardCommand? {
    val prefix = Regex("^\\s*转发给\\s*").find(text) ?: return null
    val rest = text.substring(prefix.range.last + 1).trim()
    fun names(runtime: DeviceRuntime) = listOfNotNull(runtime.id, runtime.displayName, runtime.type, runtime.typeDisplayName)
    fun delimiter(char: Char) = char.isWhitespace() || char in "，,：:；;。"
    val name = runtimes.flatMap(::names).distinct().sortedByDescending { it.length }.firstOrNull { candidate ->
        rest.startsWith(candidate, ignoreCase = true) && (rest.length == candidate.length || delimiter(rest[candidate.length]))
    }
    require(name != null) { "未找到目标 AI，请使用设备上的完整 AI 名称或标识" }
    val matches = runtimes.filter { runtime -> names(runtime).any { it.equals(name, ignoreCase = true) } }
    require(matches.size == 1) { "AI 名称重复，请使用完整 AI 标识" }
    val instructions = rest.drop(name.length).trimStart(::delimiter).trim().ifEmpty { "请审核当前代码和任务结果，指出问题及后续建议。" }
    return ForwardCommand(matches.single().id, instructions)
}

fun taskGroupChain(groups: List<TaskGroup>, root: String?): Set<String> {
    if (root == null) return emptySet()
    val ids = mutableSetOf(root)
    var changed: Boolean
    do {
        val before = ids.size
        groups.filter { it.id in ids }.mapNotNull { it.sourceId }.forEach(ids::add)
        groups.filter { it.sourceId in ids }.forEach { ids.add(it.id) }
        changed = ids.size != before
    } while (changed)
    return ids
}
