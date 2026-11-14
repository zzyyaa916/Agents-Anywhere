from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any

from connector.runtime_protocol.host import RuntimeHostClient, UploadProgress
from connector.runtime_protocol.instance_models import (
    RuntimeInstanceSpec,
    RuntimeSourceKey,
)
from connector.runtime_protocol.model_connection import ModelConnectionStatus
from connector.runtime_protocol.models import (
    PreparedSessionTimelineSync,
    RuntimeAttachment,
    RuntimeAttachmentContent,
    RuntimeCapability,
    RuntimeCapabilitySet,
    RuntimeCommand,
    RuntimeCommandResult,
    RuntimeConfig,
    RuntimeIdentity,
    RuntimeModelCatalog,
    RuntimeOperationResult,
    RuntimePermissionCatalog,
    RuntimeStatus,
    RuntimeTimelineItem,
    RuntimeTimelineSnapshot,
    SessionMeta,
    SessionNotice,
    SessionSourceObservation,
    SessionState,
)
from connector.runtime_protocol.protocol import AgentRuntime
from connector.runtime_protocol.session_selections import SessionSelectionStore
from connector.runtime_protocol.workflows import (
    RuntimeWorkflowRequest,
    RuntimeWorkflowResult,
)


def _instance_metadata(
    instance: RuntimeInstanceSpec,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        **dict(metadata or {}),
        "runtimeType": instance.runtime_type,
        "runtimeId": instance.runtime_id,
    }


def _capability_for_instance(
    capability: RuntimeCapability,
    instance: RuntimeInstanceSpec,
) -> RuntimeCapability:
    return replace(
        capability,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        metadata=_instance_metadata(instance, capability.metadata),
    )


def runtime_capabilities_for_instance(
    value: RuntimeCapabilitySet,
    instance: RuntimeInstanceSpec,
) -> RuntimeCapabilitySet:
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        capabilities=tuple(
            _capability_for_instance(capability, instance)
            for capability in value.capabilities
        ),
        metadata=_instance_metadata(instance, value.metadata),
    )


def runtime_config_for_instance(
    value: RuntimeConfig,
    instance: RuntimeInstanceSpec,
) -> RuntimeConfig:
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        metadata=_instance_metadata(instance, value.metadata),
    )


def timeline_item_for_instance(
    item: RuntimeTimelineItem,
    instance: RuntimeInstanceSpec,
) -> RuntimeTimelineItem:
    source = {
        **dict(item.source),
        "runtime": instance.runtime_type,
        "runtimeType": instance.runtime_type,
        "runtimeId": instance.runtime_id,
    }
    return replace(
        item,
        source=source,
        metadata=_instance_metadata(instance, item.metadata),
    )


def session_meta_for_instance(
    value: SessionMeta,
    instance: RuntimeInstanceSpec,
) -> SessionMeta:
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        metadata=_instance_metadata(instance, value.metadata),
    )


def session_state_for_instance(
    value: SessionState,
    instance: RuntimeInstanceSpec,
) -> SessionState:
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        metadata=_instance_metadata(instance, value.metadata),
    )


def session_notice_for_instance(
    value: SessionNotice,
    instance: RuntimeInstanceSpec,
) -> SessionNotice:
    source = {
        **dict(value.source),
        "runtime": instance.runtime_type,
        "runtimeType": instance.runtime_type,
        "runtimeId": instance.runtime_id,
    }
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        source=source,
        metadata=_instance_metadata(instance, value.metadata),
    )


def timeline_snapshot_for_instance(
    value: RuntimeTimelineSnapshot,
    instance: RuntimeInstanceSpec,
) -> RuntimeTimelineSnapshot:
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
        items=tuple(timeline_item_for_instance(item, instance) for item in value.items),
        metadata=_instance_metadata(instance, value.metadata),
    )


def session_source_observation_for_instance(
    value: SessionSourceObservation,
    instance: RuntimeInstanceSpec,
) -> SessionSourceObservation:
    return replace(
        value,
        runtime=instance.runtime_type,
        runtime_id=instance.runtime_id,
    )


async def with_planning_capabilities(capabilities: RuntimeCapabilitySet, port, external_session_id: str | None = None) -> RuntimeCapabilitySet:
    if port is None:
        return capabilities
    from connector.runtime_protocol.models import RuntimeCapability
    existing = next((item for item in capabilities.capabilities if item.capability_id == "session.planning"), None)
    native_available = (existing.metadata if existing else {}).get("nativePlanningAvailable")
    supported = native_available if isinstance(native_available, bool) else await port.available(capabilities.session_id or "", external_session_id)
    names = ("session.planning", "session.plan_document", "session.plan_review")
    items = [item for item in capabilities.capabilities if item.capability_id not in names]
    for name in names:
        items.append(RuntimeCapability(
            capability_id=name, scope="session" if capabilities.session_id else "runtime",
            runtime=capabilities.runtime, session_id=capabilities.session_id, supported=supported,
            available=supported,
            metadata={"contentStreaming": port.content_streaming}))
    return replace(capabilities, capabilities=tuple(items))


@dataclass(frozen=True, slots=True)
class RuntimeInstanceHost(RuntimeHostClient):
    """Bind runtime-to-Connector effects to one immutable instance identity."""

    base: RuntimeHostClient
    instance: RuntimeInstanceSpec
    source_key: RuntimeSourceKey | None = None
    status_reporter: (
        Callable[
            [str, str, Mapping[str, Any] | None, Mapping[str, Any] | None],
            Awaitable[None],
        ]
        | None
    ) = None
    selection_store: SessionSelectionStore | None = None

    async def claude_usage_observer(self):
        return await self.base.claude_usage_observer()

    async def observe_planning(self, observation) -> None:
        await RuntimeHostClient.observe_planning(self, observation)

    async def validate_planning_document(self, session_id: str, text: str) -> bool:
        return await RuntimeHostClient.validate_planning_document(self, session_id, text)

    async def prepare_planning_turn(self, session_id: str, external_id: str | None) -> bool:
        return await RuntimeHostClient.prepare_planning_turn(self, session_id, external_id)

    async def publish_planning(self, snapshot: dict, durable: bool = False) -> None:
        await self.base.publish_planning({**snapshot, "runtimeId": self.instance.runtime_id,
                                          "runtime": self.instance.runtime_type}, durable)

    @property
    def supports_sync_state(self) -> bool:
        return bool(getattr(self.base, "supports_sync_state", False))

    @property
    def connector_id(self) -> str:
        return self.base.connector_id

    @property
    def runtime_id(self) -> str:
        return self.instance.runtime_id

    @property
    def session_namespace(self) -> str:
        if self.instance.runtime_id == self.instance.runtime_type:
            return self.connector_id
        namespace = self.instance.runtime_id
        if self.source_key is not None:
            namespace = f"{namespace}:{_source_key_digest(self.source_key)}"
        return f"{self.connector_id}:{self.instance.runtime_type}:{namespace}"

    async def publish_runtime_snapshot(
        self, runtime: str, session_id: str, meta: dict[str, Any], items: Iterable[dict[str, Any]],
        *, runtime_id: str | None = None, on_progress: UploadProgress | None = None, ordered: bool = True,
    ) -> None:
        self._validate_native_runtime(runtime)
        kwargs = {} if ordered else {"ordered": False}
        await self.base.publish_runtime_snapshot(
            runtime, session_id, meta, items, runtime_id=self.instance.runtime_id, on_progress=on_progress, **kwargs,
        )

    async def publish_runtime_notifications(
        self, runtime: str, notifications: list[dict[str, Any]], *, runtime_id: str | None = None,
        on_progress: UploadProgress | None = None,
    ) -> None:
        self._validate_native_runtime(runtime)
        kwargs = {"on_progress": on_progress} if on_progress is not None else {}
        if self.selection_store is not None:
            notifications = [dict(notice) for notice in notifications]
            for notice in notifications:
                if notice.get("method") != "session.state.updated":
                    continue
                params = notice.get("params")
                if not isinstance(params, dict) or not isinstance(params.get("sessionId"), str):
                    continue
                params = dict(params)
                params["selections"] = await self.selection_store.observed(params["sessionId"], params.get("selections"))
                notice["params"] = params
        await self.base.publish_runtime_notifications(runtime, notifications, runtime_id=self.instance.runtime_id, **kwargs)

    async def session_meta_upsert(
        self,
        session_id: str,
        runtime: str,
        external_session_id: str | None = None,
        title: str | None = None,
        cwd: str | None = None,
        ordering_time: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._validate_native_runtime(runtime)
        await self.base.session_meta_upsert(
            session_id=session_id,
            runtime=self.instance.runtime_type,
            external_session_id=external_session_id,
            title=title,
            cwd=cwd,
            ordering_time=ordering_time,
            metadata=self.instance_metadata(metadata),
        )

    async def session_state_update(
        self,
        session_id: str,
        runtime: str,
        status: RuntimeStatus | None = None,
        selections: Mapping[str, str | None] | None = None,
        external_session_id: str | None = None,
        status_reason: str | None = None,
        error: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._validate_native_runtime(runtime)
        if self.selection_store is not None:
            selections = await self.selection_store.observed(session_id, selections)
        await self.base.session_state_update(
            session_id=session_id,
            runtime=self.instance.runtime_type,
            status=status,
            selections=selections,
            external_session_id=external_session_id,
            status_reason=status_reason,
            error=error,
            metadata=self.instance_metadata(metadata),
        )

    async def session_source_update(
        self,
        observation: SessionSourceObservation,
    ) -> None:
        self._validate_native_runtime(observation.runtime)
        await self.base.session_source_update(
            session_source_observation_for_instance(observation, self.instance)
        )

    async def session_turn_ended(
        self,
        session_id: str,
        runtime: str,
        external_session_id: str | None = None,
        turn_id: str | None = None,
        outcome: str = "completed",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._validate_native_runtime(runtime)
        await self.base.session_turn_ended(
            session_id=session_id,
            runtime=self.instance.runtime_type,
            external_session_id=external_session_id,
            turn_id=turn_id,
            outcome=outcome,
            metadata=self.instance_metadata(metadata),
        )

    async def publish_goal(self, snapshot: dict, durable: bool = False) -> None:
        await self.base.publish_goal(
            {
                **snapshot,
                "runtime": self.instance.runtime_type,
                "runtimeId": self.instance.runtime_id,
            },
            durable=durable,
        )

    async def prepare_goal_creation(
        self, session_id, external_id, content, attachments, operation_id
    ):
        return await RuntimeHostClient.prepare_goal_creation(
            self, session_id, external_id, content, attachments, operation_id
        )

    async def planning_capabilities(
        self, capabilities: RuntimeCapabilitySet
    ) -> RuntimeCapabilitySet:
        capabilities = await with_planning_capabilities(
            capabilities, getattr(self, "_planning_port", None)
        )
        return await with_goal_capabilities(
            capabilities, getattr(self, "_goal_port", None)
        )

    async def runtime_capabilities_update(
        self,
        capabilities: RuntimeCapabilitySet,
    ) -> None:
        await self.base.runtime_capabilities_update(
            runtime_capabilities_for_instance(await self.planning_capabilities(capabilities), self.instance)
        )

    async def session_capabilities_update(
        self,
        capabilities: RuntimeCapabilitySet,
    ) -> None:
        await self.base.session_capabilities_update(
            runtime_capabilities_for_instance(await self.planning_capabilities(capabilities), self.instance)
        )

    async def model_catalog_update(self, catalog: RuntimeModelCatalog) -> None:
        await self.base.model_catalog_update(
            replace(
                catalog,
                runtime=self.instance.runtime_type,
                runtime_id=self.instance.runtime_id,
            )
        )

    async def permission_catalog_update(
        self,
        catalog: RuntimePermissionCatalog,
    ) -> None:
        await self.base.permission_catalog_update(
            replace(
                catalog,
                runtime=self.instance.runtime_type,
                runtime_id=self.instance.runtime_id,
            )
        )

    async def timeline_sync(
        self,
        session_id: str,
        runtime: str,
        items: tuple[RuntimeTimelineItem, ...],
        external_session_id: str | None = None,
        complete: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self._validate_native_runtime(runtime)
        await self.base.timeline_sync(
            session_id=session_id,
            runtime=self.instance.runtime_type,
            items=tuple(
                timeline_item_for_instance(item, self.instance) for item in items
            ),
            external_session_id=external_session_id,
            complete=complete,
            metadata=self.instance_metadata(metadata),
        )

    async def timeline_item_upsert(self, item: RuntimeTimelineItem) -> None:
        await self.base.timeline_item_upsert(
            timeline_item_for_instance(item, self.instance)
        )

    async def notice_upsert(self, notice: SessionNotice) -> None:
        await self.base.notice_upsert(
            session_notice_for_instance(notice, self.instance)
        )

    async def runtime_error(
        self,
        runtime: str,
        code: str,
        message: str,
        session_id: str | None = None,
        external_session_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self._validate_native_runtime(runtime)
        await self.base.runtime_error(
            runtime=self.instance.runtime_type,
            code=code,
            message=message,
            session_id=session_id,
            external_session_id=external_session_id,
            details=self.instance_metadata(details),
        )

    async def runtime_health_update(
        self,
        status: str,
        error: Mapping[str, Any] | None = None,
        phase: Mapping[str, Any] | None = None,
    ) -> None:
        if self.status_reporter is None:
            return
        await self.status_reporter(self.instance.runtime_id, status, error, phase)

    async def attachment_download(
        self,
        session_id: str,
        file_id: str,
    ) -> RuntimeAttachmentContent:
        return await self.base.attachment_download(session_id, file_id)

    async def sync_state_read(self, key: str) -> Mapping[str, Any] | None:
        return await self.base.sync_state_read(self.instance_sync_key(key))

    @property
    def runtime_kv(self):
        return self.base.runtime_kv

    async def prepare_runtime_host(self, runtime_id: str) -> RuntimeHostClient:
        if runtime_id != self.instance.runtime_id:
            raise ValueError("Cannot rebind an instance Host to another runtime")
        return replace(self, base=await self.base.prepare_runtime_host(runtime_id))

    async def sync_state_write(
        self,
        key: str,
        value: Mapping[str, Any],
    ) -> None:
        await self.base.sync_state_write(self.instance_sync_key(key), value)

    async def sync_state_delete(self, key: str) -> None:
        await self.base.sync_state_delete(self.instance_sync_key(key))

    def instance_sync_key(self, key: str) -> str:
        if self.instance.runtime_id == self.instance.runtime_type:
            return key
        type_prefix = f"{self.instance.runtime_type}/"
        suffix = key.removeprefix(type_prefix)
        namespace = self.instance.runtime_id
        if self.source_key is not None:
            namespace = f"{namespace}/{_source_key_digest(self.source_key)}"
        return f"{self.instance.runtime_type}/instances/{namespace}/{suffix}"

    def instance_metadata(
        self,
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        result = _instance_metadata(self.instance, metadata)
        if self.source_key is not None:
            result["runtimeSource"] = {
                "kind": self.source_key.kind,
                "key": self.source_key.key,
            }
        return result

    def _validate_native_runtime(self, runtime: str) -> None:
        if runtime != self.instance.runtime_type:
            raise ValueError(
                f"runtime host call used type {runtime!r}; expected "
                f"{self.instance.runtime_type!r}"
            )


@dataclass(frozen=True, slots=True)
class RuntimeInstance(AgentRuntime):
    """Expose one native provider runtime without changing its provider type."""

    instance: RuntimeInstanceSpec
    native_runtime: AgentRuntime
    selection_store: SessionSelectionStore | None = None

    async def _model_choice_error(self, selections):
        if self.selection_store is None:
            return None
        model = (selections or {}).get("model")
        if isinstance(model, str) and model.strip():
            try:
                catalog = await self.native_runtime.list_model_catalog(limit=200)
            except Exception:  # noqa: BLE001 - fail closed on catalog failure
                return RuntimeOperationResult(
                    ok=False, code="session_model_selection_required",
                    message="模型目录暂时不可用，无法确认模型和思考强度；请重试或重新选择，不会使用默认模型。",
                )
            for item in catalog.models:
                if not item.enabled:
                    continue
                if item.selection_id == model:
                    if any(effort.enabled for effort in item.reasoning_items):
                        return RuntimeOperationResult(
                            ok=False, code="session_model_selection_required",
                            message="请明确选择模型的思考强度后再发送；不会使用默认思考强度。",
                        )
                    return None
                if any(effort.selection_id == model and effort.enabled for effort in item.reasoning_items):
                    return None
            return RuntimeOperationResult(
                ok=False, code="session_model_selection_required",
                message="所选模型或思考强度不在当前模型目录中，请重新选择；不会使用默认模型。",
            )
        try:
            capabilities = await self.native_runtime.get_runtime_capabilities()
        except Exception:  # noqa: BLE001 - fail closed on capability failure
            return RuntimeOperationResult(
                ok=False, code="session_model_selection_required",
                message="无法确认此会话的模型和思考强度，请先明确选择后再发送；不会使用默认模型。",
            )
        if any(item.capability_id == "catalog.model" and item.supported for item in capabilities.capabilities):
            return RuntimeOperationResult(
                ok=False, code="session_model_selection_required",
                message="无法确认此会话的模型和思考强度，请先明确选择后再发送；不会使用默认模型。",
            )
        return None

    async def prepare_history_deletion(self, target):
        prepare = getattr(self.native_runtime, "prepare_history_deletion", None)
        if not callable(prepare):
            raise ValueError("native_history_deletion_unsupported")  # noqa: TRY004 - stable protocol code
        return await prepare(target)

    async def delete_session_history(self, target):
        delete = getattr(self.native_runtime, "delete_session_history", None)
        if not callable(delete):
            raise ValueError("native_history_deletion_unsupported")  # noqa: TRY004 - stable protocol code
        return await delete(target)

    async def list_scoped_model_catalog(self, session_id: str, query: str | None = None, limit: int = 100) -> RuntimeModelCatalog:
        catalog = await self.native_runtime.list_scoped_model_catalog(session_id, query=query, limit=limit)
        return replace(catalog, runtime=self.instance.runtime_type, runtime_id=self.instance.runtime_id)

    async def execute_workflow(self, request: RuntimeWorkflowRequest) -> RuntimeWorkflowResult:
        return await self.native_runtime.execute_workflow(request)

    async def get_session_configuration(self, session_id: str) -> dict[str, Any]:
        return await self.native_runtime.get_session_configuration(session_id)

    async def update_session_configuration(self, session_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        return await self.native_runtime.update_session_configuration(session_id, values)

    @property
    def goals(self):
        return self.native_runtime.goals

    @property
    def planning(self):
        return self.native_runtime.planning


    def model_connection_status(self) -> ModelConnectionStatus | None:
        return self.native_runtime.model_connection_status()

    @property
    def sync_mode(self) -> str:
        return self.native_runtime.sync_mode

    async def resynchronize(self, session_id: str | None = None, external_session_id: str | None = None) -> None:
        await self.native_runtime.resynchronize(session_id, external_session_id)

    def __post_init__(self) -> None:
        if self.native_runtime.identity.runtime != self.instance.runtime_type:
            raise ValueError(
                "native runtime identity does not match the instance runtime type"
            )

    @property
    def identity(self) -> RuntimeIdentity:
        identity = self.native_runtime.identity
        return replace(
            identity,
            runtime=self.instance.runtime_type,
            runtime_id=self.instance.runtime_id,
            display_name=self.instance.name,
        )

    async def start(self) -> None:
        await self.native_runtime.start()

    async def stop(self) -> None:
        if self.planning is not None:
            await self.planning.close()
        await self.native_runtime.stop()

    async def apply_model_setting(self, config: RuntimeConfig) -> bool:
        return await self.native_runtime.apply_model_setting(config)

    async def get_config(self) -> RuntimeConfig:
        return runtime_config_for_instance(
            await self.native_runtime.get_config(),
            self.instance,
        )

    async def get_runtime_capabilities(self) -> RuntimeCapabilitySet:
        capabilities = await self.native_runtime.get_runtime_capabilities()
        if self.planning is not None:
            capabilities = await with_planning_capabilities(
                capabilities, self.planning.port
            )
        capabilities = await with_goal_capabilities(
            capabilities, self.goals.port if self.goals else None
        )
        return runtime_capabilities_for_instance(capabilities, self.instance)

    async def list_model_catalog(
        self,
        query: str | None = None,
        limit: int = 100,
    ) -> RuntimeModelCatalog:
        catalog = await self.native_runtime.list_model_catalog(query=query, limit=limit)
        return replace(
            catalog,
            runtime=self.instance.runtime_type,
            runtime_id=self.instance.runtime_id,
        )

    async def list_permission_catalog(
        self,
        query: str | None = None,
        limit: int = 100,
    ) -> RuntimePermissionCatalog:
        catalog = await self.native_runtime.list_permission_catalog(
            query=query,
            limit=limit,
        )
        return replace(
            catalog,
            runtime=self.instance.runtime_type,
            runtime_id=self.instance.runtime_id,
        )

    async def list_sessions(
        self,
        limit: int = 100,
        cursor: str | None = None,
        force: bool = False,
    ) -> tuple[SessionMeta, ...]:
        sessions = await self.native_runtime.list_sessions(
            limit=limit,
            cursor=cursor,
            force=force,
        )
        return tuple(
            session_meta_for_instance(session, self.instance) for session in sessions
        )

    async def list_complete_session_inventory(
        self,
        page_size: int = 100,
        force: bool = False,
    ) -> tuple[SessionMeta, ...]:
        sessions = await self.native_runtime.list_complete_session_inventory(
            page_size=page_size,
            force=force,
        )
        return tuple(
            session_meta_for_instance(session, self.instance) for session in sessions
        )

    def supports_complete_session_inventory(self) -> bool:
        return self.native_runtime.supports_complete_session_inventory()

    async def get_session_snapshot(
        self,
        session_id: str,
        external_session_id: str | None = None,
        limit: int | None = None,
    ) -> RuntimeTimelineSnapshot:
        snapshot = await self.native_runtime.get_session_snapshot(
            session_id=session_id,
            external_session_id=external_session_id,
            limit=limit,
        )
        return timeline_snapshot_for_instance(snapshot, self.instance)

    async def sync_session_timeline(
        self,
        session_id: str,
        external_session_id: str | None = None,
    ) -> bool:
        return await self.native_runtime.sync_session_timeline(
            session_id=session_id,
            external_session_id=external_session_id,
        )

    async def prepare_session_timeline_sync(
        self,
        session_id: str,
        external_session_id: str | None = None,
    ) -> PreparedSessionTimelineSync | None:
        prepared = await self.native_runtime.prepare_session_timeline_sync(
            session_id=session_id,
            external_session_id=external_session_id,
        )
        if prepared is None or prepared.snapshot is None:
            return prepared
        return replace(
            prepared,
            snapshot=timeline_snapshot_for_instance(
                prepared.snapshot,
                self.instance,
            ),
        )

    async def get_session_state(
        self,
        session_id: str,
        external_session_id: str | None = None,
    ) -> SessionState | None:
        state = await self.native_runtime.get_session_state(
            session_id,
            external_session_id,
        )
        if state is not None and self.selection_store is not None:
            metadata = dict(state.metadata)
            if await self.selection_store.model_is_confirmed(session_id):
                saved = await self.selection_store.read(session_id)
                if state.selections.get("model") != saved.get("model") or metadata.get("selection_effect") not in {"applied", "next_turn"}:
                    metadata["selection_effect"] = "next_turn"
            state = replace(state, selections=await self.selection_store.observed(session_id, state.selections), metadata=metadata)
        return (
            None if state is None else session_state_for_instance(state, self.instance)
        )

    async def get_session_notices(
        self,
        session_id: str,
        external_session_id: str | None = None,
    ) -> tuple[SessionNotice, ...]:
        notices = await self.native_runtime.get_session_notices(
            session_id,
            external_session_id,
        )
        return tuple(
            session_notice_for_instance(notice, self.instance) for notice in notices
        )

    async def get_session_capabilities(
        self,
        session_id: str,
        external_session_id: str | None = None,
    ) -> RuntimeCapabilitySet:
        capabilities = await self.native_runtime.get_session_capabilities(
            session_id,
            external_session_id,
        )
        if self.planning is not None:
            capabilities = await with_planning_capabilities(
                capabilities, self.planning.port, external_session_id
            )
        capabilities = await with_goal_capabilities(
            capabilities, self.goals.port if self.goals else None
        )
        return runtime_capabilities_for_instance(capabilities, self.instance)

    async def create_and_start_session(
        self,
        session_id: str,
        content: str,
        title: str | None = None,
        cwd: str | None = None,
        selections: Mapping[str, str | None] | None = None,
        attachments: tuple[RuntimeAttachment, ...] = (),
        client_message_id: str | None = None,
        *, runtime_options: Mapping[str, Any] | None = None,
    ) -> RuntimeOperationResult:
        effective = await self.selection_store.for_turn(session_id, selections) if self.selection_store is not None else selections
        if error := await self._model_choice_error(effective):
            return error
        result = await self.native_runtime.create_and_start_session(
            session_id=session_id,
            content=content,
            title=title,
            cwd=cwd,
            selections=effective,
            attachments=attachments,
            client_message_id=client_message_id,
            **({"runtime_options": runtime_options} if runtime_options else {}),
        )
        if result.ok and self.selection_store is not None:
            await self.selection_store.remember(session_id, effective)
        return result

    async def start_turn(
        self,
        session_id: str,
        external_session_id: str | None,
        content: str,
        selections: Mapping[str, str | None] | None = None,
        attachments: tuple[RuntimeAttachment, ...] = (),
        client_message_id: str | None = None,
        cwd: str | None = None,
    ) -> RuntimeOperationResult:
        effective = await self.selection_store.for_turn(session_id, selections) if self.selection_store is not None else selections
        if self.selection_store is not None:
            saved = await self.selection_store.read(session_id)
            if saved.get("model") and not await self.selection_store.model_is_confirmed(session_id):
                return RuntimeOperationResult(
                    ok=False, code="session_model_selection_required",
                    message="模型选择尚未确认，请重新选择后再发送；不会使用默认模型。",
                )
        if error := await self._model_choice_error(effective):
            return error
        result = await self.native_runtime.start_turn(
            session_id=session_id,
            external_session_id=external_session_id,
            content=content,
            selections=effective,
            attachments=attachments,
            client_message_id=client_message_id,
            cwd=cwd,
        )
        return result

    async def steer_turn(
        self,
        session_id: str,
        external_session_id: str | None,
        content: str,
        attachments: tuple[RuntimeAttachment, ...] = (),
        client_message_id: str | None = None,
    ) -> RuntimeOperationResult:
        return await self.native_runtime.steer_turn(
            session_id=session_id,
            external_session_id=external_session_id,
            content=content,
            attachments=attachments,
            client_message_id=client_message_id,
        )

    async def interrupt_session(
        self,
        session_id: str,
        reason: str | None = None,
    ) -> RuntimeOperationResult:
        return await self.native_runtime.interrupt_session(session_id, reason)

    async def update_session_selections(
        self,
        session_id: str,
        external_session_id: str | None,
        selections: Mapping[str, str | None],
    ) -> RuntimeOperationResult:
        async with (self.selection_store.change(session_id) if self.selection_store is not None else nullcontext()):
            if self.selection_store is not None and "model" in selections:
                await self.selection_store.require_reselection(session_id)
                if error := await self._model_choice_error(selections):
                    return error
            effective = await self.selection_store.resolve(session_id, selections) if self.selection_store is not None else selections
            try:
                result = await self.native_runtime.update_session_selections(
                    session_id,
                    external_session_id,
                    effective,
                )
            except Exception:
                if self.selection_store is not None and "model" in selections:
                    await self.selection_store.require_reselection(session_id)
                raise
            if result.ok and self.selection_store is not None:
                reported = result.result.get("selections") if isinstance(result.result, Mapping) else None
                canonical = dict(reported) if isinstance(reported, Mapping) else dict(effective)
                await self.selection_store.remember(session_id, canonical)
                raw_state = result.result.get("state")
                raw_metadata = raw_state.get("metadata", {}) if isinstance(raw_state, Mapping) else {}
                effect = raw_metadata.get("selection_effect") if isinstance(raw_metadata, Mapping) else None
                if isinstance(result.result.get("applied"), bool):
                    effect = "applied" if result.result["applied"] else "next_turn"
                # Persisted choices are guaranteed for the next turn; this is not an applied-now claim.
                if effect not in {"applied", "next_turn"}:
                    effect = "next_turn"
                result = replace(result, result={**result.result, "selectionEffect": effect,
                    "selections": canonical})
            elif self.selection_store is not None and "model" in selections:
                await self.selection_store.require_reselection(session_id)
            return result

    async def list_commands(
        self,
        session_id: str,
        external_session_id: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> tuple[RuntimeCommand, ...]:
        return await self.native_runtime.list_commands(
            session_id=session_id,
            external_session_id=external_session_id,
            query=query,
            limit=limit,
        )

    async def list_runtime_commands(
        self,
        limit: int = 100,
    ) -> tuple[RuntimeCommand, ...]:
        return await self.native_runtime.list_runtime_commands(limit=limit)

    async def execute_command(
        self,
        session_id: str,
        command: str,
        external_session_id: str | None = None,
        raw: str | None = None,
        args: tuple[str, ...] = (),
    ) -> RuntimeCommandResult:
        return await self.native_runtime.execute_command(
            session_id=session_id,
            command=command,
            external_session_id=external_session_id,
            raw=raw,
            args=args,
        )

    async def respond_interaction(
        self,
        session_id: str,
        notice_id: str,
        action_id: str,
        input_data: Mapping[str, Any] | None = None,
    ) -> RuntimeOperationResult:
        return await self.native_runtime.respond_interaction(
            session_id=session_id,
            notice_id=notice_id,
            action_id=action_id,
            input_data=input_data,
        )


def _source_key_digest(source_key: RuntimeSourceKey) -> str:
    payload = f"{source_key.kind}\0{source_key.key}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


async def with_goal_capabilities(capabilities, port):
    if port is None:
        return capabilities
    from connector.runtime_protocol.models import RuntimeCapability

    supported = await port.available(capabilities.session_id or "")
    capability = RuntimeCapability(
        capability_id="session.goal",
        runtime=capabilities.runtime,
        session_id=capabilities.session_id,
        scope="session" if capabilities.session_id else "runtime",
        supported=supported,
        available=supported,
    )
    return replace(
        capabilities,
        capabilities=tuple(
            item
            for item in capabilities.capabilities
            if item.capability_id != "session.goal"
        )
        + (capability,),
    )
