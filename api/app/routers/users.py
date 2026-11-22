import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import require_role
from ..models import User
from ..schemas import UserCreateIn, UserOut, UserUpdateIn
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

# Toda query filtra por admin.org_id (vindo do usuário autenticado, nunca do cliente).


@router.get("", response_model=list[UserOut])
async def list_users(admin: User = Depends(require_role("admin")),
                     session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(User).where(User.org_id == admin.org_id).order_by(User.created_at))
    return list(rows)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateIn, admin: User = Depends(require_role("admin")),
                      session: AsyncSession = Depends(get_session)):
    email = body.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")
    user = User(org_id=admin.org_id, email=email,
                password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    await session.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdateIn,
                      admin: User = Depends(require_role("admin")),
                      session: AsyncSession = Depends(get_session)):
    # 404 (e não 403) para usuário de outra org: não revela que o id existe.
    user = await session.scalar(
        select(User).where(User.id == user_id, User.org_id == admin.org_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")

    if user.id == admin.id and (body.role == "member" or body.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Você não pode rebaixar ou desativar a si mesmo")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    await session.commit()
    return user
