from fastapi import APIRouter, Depends

from app.models.schemas import TokenResponse, UserLoginRequest, UserPublic, UserRegisterRequest
from app.services.auth_service import auth_service, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(request: UserRegisterRequest) -> TokenResponse:
    user = await auth_service.register_user(request.name, request.email, request.password)
    token = auth_service.create_access_token(user["id"])
    return TokenResponse(access_token=token, user=auth_service.to_public_user(user))


@router.post("/login", response_model=TokenResponse)
async def login(request: UserLoginRequest) -> TokenResponse:
    user = await auth_service.authenticate_user(request.email, request.password)
    token = auth_service.create_access_token(user["id"])
    return TokenResponse(access_token=token, user=auth_service.to_public_user(user))


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserPublic:
    return auth_service.to_public_user(current_user)
