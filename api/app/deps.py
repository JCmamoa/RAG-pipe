import uuid

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session, org_session
from .models import User
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthError(Exception):
    pass


async def authenticate_token(token: str, session: AsyncSession) -> tuple[User, dict]:
    """Valida o JWT e recarrega o usuário do banco (fonte de verdade de role/org/is_active).

    Usado pelo HTTP e pelo WebSocket.
    """
    try:
        payload = decode_token(token)
        user_id = uuid.UUID(payload["sub"])
        token_org_id = uuid.UUID(payload["org_id"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise AuthError("token inválido ou expirado")
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.org_id != token_org_id:
        raise AuthError("usuário inativo ou token incoerente")
    return user, payload


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        user, _ = await authenticate_token(token, session)
    except AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido ou expirado",
                            headers={"WWW-Authenticate": "Bearer"})
    request.state.user_id = str(user.id)  # lido pelo middleware de log de acesso
    request.state.org_id = str(user.org_id)
    return user


def require_role(*roles: str):
    async def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permissão insuficiente")
        return user
    return checker


async def get_org_session(user: User = Depends(get_current_user)):
    """Sessão com tenant fixado (RLS ativo). Use SEMPRE para documents e chunks.

    Handlers que escrevem devem chamar `await session.commit()` explicitamente.
    """
    async with org_session(user.org_id) as session:
        yield session
