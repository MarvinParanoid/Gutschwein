from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.models import User
from app.schemas import MeOut, UserOut

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/me", response_model=MeOut)
async def me(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    members = (await session.execute(select(User).order_by(User.id))).scalars().all()
    return MeOut(
        user=UserOut.model_validate(user),
        members=[UserOut.model_validate(m) for m in members],
    )
