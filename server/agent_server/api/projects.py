from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_server.core.history_deletion import (
    DeviceCleanupIncomplete,
    HistoryDeletionConflict,
    cleanup_failure_message,
)
from agent_server.core.models import (
    ArchiveAllRequest,
    ArchiveAllResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDeleteResponse,
    ProjectListResponse,
    ProjectPatchRequest,
    ProjectResponse,
    ProjectSessionListResponse,
)
from agent_server.core.utc import utc_now
from agent_server.deps import (
    current_user_id,
    get_rpc,
    get_session_runtime_state_cache,
    get_store,
    get_terminal_broker,
    get_timeline_broker,
    get_timeline_write_buffer,
)
from agent_server.infra.connector_rpc import (
    ConnectorOfflineError,
    ConnectorRpcError,
    ConnectorRpcManager,
)
from agent_server.infra.repositories.facade import Store
from agent_server.infra.repositories.projects import ProjectNameConflictError
from agent_server.infra.terminal_broker import TerminalBroker
from agent_server.infra.timeline_broker import TimelineBroker
from agent_server.services.connector_presence import (
    with_effective_session_connector_statuses,
)
from agent_server.services.dashboard_events import publish_dashboard_changed
from agent_server.services.history_deletion import (
    abandon_device_cleanup,
    delete_history_data,
)
from agent_server.services.project_directories import create_project_directory
from agent_server.services.session_meta_projection import (
    project_session_meta_for_dashboard,
)
from agent_server.services.session_runtime_state_cache import SessionRuntimeStateCache
from agent_server.services.timeline_write_buffer import TimelineWriteBuffer

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
) -> ProjectListResponse:
    return ProjectListResponse(
        projects=await store.list_projects(user_id=user_id),
        serverTime=utc_now(),
    )


@router.post("", response_model=ProjectCreateResponse)
async def create_project(
    payload: ProjectCreateRequest,
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    manager: ConnectorRpcManager = Depends(get_rpc),
    broker: TimelineBroker = Depends(get_timeline_broker),
) -> ProjectCreateResponse:
    try:
        if payload.manuallyCreated:
            project = await create_project_directory(payload, user_id=user_id, store=store, manager=manager)
        else:
            project = await store.create_project(
                user_id=user_id,
                connector_id=payload.connectorId,
                name=payload.name,
                workspace_path=payload.workspacePath,
                manually_created=payload.manuallyCreated,
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="connector not found") from None
    except ProjectNameConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_name_conflict",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConnectorRpcError as exc:
        message = "同名文件夹已存在，请选择其他项目名称" if exc.code == "FileExistsError" else "无法创建项目文件夹，请检查目录权限并确认 Connector 已更新"
        raise HTTPException(status_code=409, detail={"code": "project_directory_failed", "message": message}) from None
    except (ConnectorOfflineError, TimeoutError):
        raise HTTPException(status_code=503, detail={"code": "project_device_offline", "message": "请连接工作设备后创建项目目录"}) from None
    await publish_dashboard_changed(
        store,
        broker,
        user_id=user_id,
        connector_id=project.connectorId,
        reason="project.created",
    )
    return ProjectCreateResponse(
        project=project,
        attachedSessions=0,
        serverTime=utc_now(),
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def patch_project(
    project_id: str,
    payload: ProjectPatchRequest,
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    broker: TimelineBroker = Depends(get_timeline_broker),
) -> ProjectResponse:
    try:
        project = await store.update_project(
            project_id,
            user_id=user_id,
            name=payload.name,
            pinned=payload.pinned,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except ProjectNameConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_name_conflict",
                "message": str(exc),
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await publish_dashboard_changed(
        store,
        broker,
        user_id=user_id,
        connector_id=project.connectorId,
        reason="project.updated",
    )
    return ProjectResponse(project=project, serverTime=utc_now())


@router.get("/{project_id}/deletion-preview")
async def project_deletion_preview(project_id: str, user_id: str = Depends(current_user_id), store: Store = Depends(get_store)) -> dict:
    try:
        _, ids = await store.history_deletion_target(project_id, user_id=user_id, project=True)
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    return {"projectId": project_id, "sessionCount": len(ids), "serverTime": utc_now()}


@router.delete("/{project_id}", response_model=ProjectDeleteResponse)
async def delete_project(
    project_id: str,
    expectedSessionCount: int | None = Query(default=None, ge=0),
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    manager: ConnectorRpcManager = Depends(get_rpc),
    broker: TimelineBroker = Depends(get_timeline_broker),
    timeline_buffer: TimelineWriteBuffer = Depends(get_timeline_write_buffer),
    runtime_state_cache: SessionRuntimeStateCache = Depends(get_session_runtime_state_cache),
    terminals: TerminalBroker = Depends(get_terminal_broker),
) -> ProjectDeleteResponse:
    try:
        ids = await delete_history_data(project_id, user_id=user_id, project=True, store=store,
            runtime_state_cache=runtime_state_cache, timeline_buffer=timeline_buffer, terminals=terminals, expected_count=expectedSessionCount, manager=manager)
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except HistoryDeletionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except (ConnectorOfflineError, ConnectorRpcError, TimeoutError, DeviceCleanupIncomplete) as exc:
        raise HTTPException(status_code=503, detail={"code": "deletion_cleanup_failed", "message": cleanup_failure_message(exc, "删除清理未完成，请重试")}) from None
    await publish_dashboard_changed(store, broker, user_id=user_id, reason="project.deleted")
    return ProjectDeleteResponse(projectId=project_id, detachedSessions=0, deletedSessions=len(ids), serverTime=utc_now())


@router.delete("/{project_id}/contents", response_model=ProjectDeleteResponse)
async def delete_project_contents(
    project_id: str,
    expectedSessionCount: int | None = Query(default=None, ge=0),
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    manager: ConnectorRpcManager = Depends(get_rpc),
    broker: TimelineBroker = Depends(get_timeline_broker),
    timeline_buffer: TimelineWriteBuffer = Depends(get_timeline_write_buffer),
    runtime_state_cache: SessionRuntimeStateCache = Depends(get_session_runtime_state_cache),
    terminals: TerminalBroker = Depends(get_terminal_broker),
) -> ProjectDeleteResponse:
    try:
        ids = await delete_history_data(project_id, user_id=user_id, project=True, store=store,
            runtime_state_cache=runtime_state_cache, timeline_buffer=timeline_buffer, terminals=terminals,
            expected_count=expectedSessionCount, manager=manager, delete_contents=True)
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except HistoryDeletionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except (ConnectorOfflineError, ConnectorRpcError, TimeoutError, DeviceCleanupIncomplete) as exc:
        raise HTTPException(status_code=503, detail={"code": "device_cleanup_incomplete", "message": cleanup_failure_message(exc, "设备文件未清理完成：请确认设备在线、Connector/原生代理已更新且会话已关闭，然后重试")}) from None
    await publish_dashboard_changed(store, broker, user_id=user_id, reason="project.deleted")
    return ProjectDeleteResponse(projectId=project_id, detachedSessions=0, deletedSessions=len(ids), serverTime=utc_now())


@router.get(
    "/{project_id}/sessions",
    response_model=ProjectSessionListResponse,
)
async def list_project_sessions(
    project_id: str,
    archived: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1),
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    manager: ConnectorRpcManager = Depends(get_rpc),
    runtime_state_cache: SessionRuntimeStateCache = Depends(
        get_session_runtime_state_cache
    ),
) -> ProjectSessionListResponse:
    try:
        sessions, has_more, next_cursor = await store.list_project_sessions_page(
            project_id,
            archived=archived,
            limit=limit,
            cursor=cursor,
            user_id=user_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ProjectSessionListResponse(
        sessions=await project_session_meta_for_dashboard(
            manager,
            runtime_state_cache,
            sessions,
        ),
        hasMore=has_more,
        nextCursor=next_cursor,
        serverTime=utc_now(),
    )


@router.post(
    "/{project_id}/sessions/archive-all",
    response_model=ArchiveAllResponse,
)
async def archive_all_project_sessions(
    project_id: str,
    payload: ArchiveAllRequest,
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    manager: ConnectorRpcManager = Depends(get_rpc),
    broker: TimelineBroker = Depends(get_timeline_broker),
) -> ArchiveAllResponse:
    try:
        sessions = await store.archive_project_sessions(
            project_id,
            payload.archived,
            scope=payload.scope,
            user_id=user_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="project not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await publish_dashboard_changed(
        store,
        broker,
        user_id=user_id,
        reason=(
            "project.sessions.archived"
            if payload.archived
            else "project.sessions.unarchived"
        ),
    )
    return ArchiveAllResponse(
        sessions=await with_effective_session_connector_statuses(manager, sessions),
        affected=len(sessions),
        serverTime=utc_now(),
    )


@router.post("/{project_id}/contents/abandon", status_code=204)
async def abandon_project_device_cleanup(
    project_id: str,
    user_id: str = Depends(current_user_id),
    store: Store = Depends(get_store),
    manager: ConnectorRpcManager = Depends(get_rpc),
    timeline_buffer: TimelineWriteBuffer = Depends(get_timeline_write_buffer),
    runtime_state_cache: SessionRuntimeStateCache = Depends(get_session_runtime_state_cache),
    terminals: TerminalBroker = Depends(get_terminal_broker),
) -> None:
    try:
        await abandon_device_cleanup(project_id, user_id=user_id, project=True, store=store,
            manager=manager, timeline_buffer=timeline_buffer, runtime_state_cache=runtime_state_cache, terminals=terminals)
    except PermissionError:
        raise HTTPException(status_code=403, detail="forbidden") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="pending cleanup not found") from None
    except (ConnectorOfflineError, ConnectorRpcError, TimeoutError, DeviceCleanupIncomplete):
        raise HTTPException(status_code=503, detail={"code": "device_cleanup_incomplete", "message": "设备未确认取消，请连接设备后重试；路径占用仍保留"}) from None
