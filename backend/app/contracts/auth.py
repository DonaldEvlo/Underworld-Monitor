from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UserContract(BaseModel):
    model_config = {"extra": "forbid"}

    id: UUID
    username: str
    active: bool
    # ⚠️ EXPOSE A L'INTERFACE A DESSEIN. Sans lui, le menu proposerait a un
    # RSSI des pages dont chaque appel repondrait 403 : une interface qui
    # promet ce qu'elle refuse est pire qu'une interface qui n'affiche rien.
    # Ce n'est PAS la garde -- la garde est serveur (api/deps.exige_role) ;
    # ceci ne fait que l'afficher.
    role: str
    created_at: datetime


class LoginRequest(BaseModel):
    model_config = {"extra": "forbid"}

    username: str
    password: str


class TokenPair(BaseModel):
    model_config = {"extra": "forbid"}

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    model_config = {"extra": "forbid"}

    refresh_token: str
