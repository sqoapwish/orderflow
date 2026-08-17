from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.audit.repository import AuditRepository
from orderflow.modules.audit.service import AuditService
from orderflow.modules.auth.dependencies import get_database_session


def get_audit_service(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AuditService:
    return AuditService(AuditRepository(session))
