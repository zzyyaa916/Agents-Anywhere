from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_server.core.task_groups import (
    TaskGroupCreate,
    TaskGroupHandoff,
    TaskGroupSelection,
)
from agent_server.deps import (
    current_user_id,
    get_rpc,
    get_session_run_service,
    get_store,
)
from agent_server.infra.connector_rpc import (
    ConnectorOfflineError,
    ConnectorRpcError,
    ConnectorRpcManager,
)
from agent_server.infra.repositories.facade import Store
from agent_server.services.session_run import SessionRunService
from agent_server.services.task_groups import TaskGroupService

router = APIRouter(prefix="/task-groups", tags=["task-groups"])


def service(
    store: Annotated[Store, Depends(get_store)],
    rpc: Annotated[ConnectorRpcManager, Depends(get_rpc)],
    sessions: Annotated[SessionRunService, Depends(get_session_run_service)],
):
    return TaskGroupService(store, rpc, sessions)


Service = Annotated[TaskGroupService, Depends(service)]
User = Annotated[str, Depends(current_user_id)]


async def invoke(action):
    try:
        return await action
    except KeyError:
        raise HTTPException(404, "任务组或来源项目不存在。") from None
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except (ConnectorOfflineError, ConnectorRpcError, TimeoutError) as error:
        raise HTTPException(
            503,
            {
                "code": "connector_unavailable",
                "message": str(error),
                "queryBeforeRetry": True,
            },
        ) from error


@router.post("")
async def create(payload: TaskGroupCreate, service: Service, user_id: User):
    return await invoke(service.create(payload, user_id=user_id))


@router.get("")
async def list_groups(
    service: Service, user_id: User, projectId: str = Query(min_length=1)
):
    await invoke(service.store.get_project(projectId, user_id=user_id))
    return {
        "groups": await invoke(
            service.store.list_task_groups(projectId, user_id=user_id)
        )
    }


@router.get("/{identifier}")
async def get(identifier: str, service: Service, user_id: User):
    return await invoke(service.get(identifier, user_id=user_id))


@router.post("/{identifier}/candidates/{slot}/start")
async def start(identifier: str, slot: int, service: Service, user_id: User):
    return await invoke(service.start(identifier, slot, user_id=user_id))


@router.get("/{identifier}/candidates/{slot}/diff")
async def diff(identifier: str, slot: int, service: Service, user_id: User):
    return await invoke(service.diff(identifier, slot, user_id=user_id))


@router.post("/{identifier}/select")
async def select(
    identifier: str, payload: TaskGroupSelection, service: Service, user_id: User
):
    return await invoke(service.select(identifier, payload.slot, user_id=user_id))


@router.post("/{identifier}/handoffs")
async def handoff(
    identifier: str, payload: TaskGroupHandoff, service: Service, user_id: User
):
    return await invoke(service.handoff(identifier, payload, user_id=user_id))
