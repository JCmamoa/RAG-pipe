from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import Organization, User
from ..rate_limit import limit_by_ip
from ..schemas import RegisterIn, TokenOut, UserOut
from ..security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
_auth_limit = Depends(limit_by_ip("auth", "rl_auth_per_min"))


def _token(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id, user.org_id, user.role))


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED,
             dependencies=[_auth_limit])
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)):
    """Cria uma organização nova e o primeiro usuário (admin).

    Cadastro aberto serve para a demo. Em produção, proteja com convite ou captcha.
    """
    email = body.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")

    org = Organization(name=body.org_name)
    session.add(org)
    await session.flush()
    user = User(org_id=org.id, email=email, password_hash=hash_password(body.password), role="admin")
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:  # corrida entre dois cadastros com o mesmo e-mail
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")
    return _token(user)


@router.post("/login", response_model=TokenOut, dependencies=[_auth_limit])
async def login(form: OAuth2PasswordRequestForm = Depends(), session: AsyncSession = Depends(get_session)):
    """Form OAuth2 (username = e-mail), para o botão Authorize do Swagger funcionar."""
    user = await session.scalar(select(User).where(User.email == form.username.lower()))
    password_ok = verify_password(user.password_hash if user else DUMMY_HASH, form.password)
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas",
                            headers={"WWW-Authenticate": "Bearer"})
    return _token(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
