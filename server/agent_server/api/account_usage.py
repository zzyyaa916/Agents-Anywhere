from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.requests import HTTPConnection

from agent_server.core.account_usage import UsageResponse
from agent_server.deps import current_user_id
from agent_server.services.account_usage import AccountUsageService

router = APIRouter(prefix="/account-usage", tags=["account-usage"])


def usage_service(conn: HTTPConnection):
    return conn.app.state.account_usage_service


@router.get("", response_model=UsageResponse)
async def cached_usage(
    user_id: Annotated[str, Depends(current_user_id)],
    service: Annotated[AccountUsageService, Depends(usage_service)],
):
    return await service.snapshot(user_id)


@router.post("/refresh", response_model=UsageResponse)
async def refresh_usage(
    user_id: Annotated[str, Depends(current_user_id)],
    service: Annotated[AccountUsageService, Depends(usage_service)],
):
    await service.refresh(user_id)
    return await service.snapshot(user_id)
