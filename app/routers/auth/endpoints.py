from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth import Token, authenticate, create_access_token

router = APIRouter(tags=["Auth"])


@router.post("/token", response_model=Token, summary="Get access token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict[str, str]:
    """Authenticate and get a JWT token."""
    if not await authenticate(form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(form_data.username)
    return {"access_token": access_token, "token_type": "bearer"}
