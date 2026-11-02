"""Compte de lecture Telegram -- reserve a l'administrateur.

Connecter un compte a la collecte est un geste de CONFIGURATION : la session
vaut le compte. Voir `services/telegram_account_service.py`.

⚠️ Aucune identite du compte n'est exposee (ni numero, ni nom, ni
identifiant) : la page n'en a pas l'usage, et une capture d'ecran de
l'interface ne doit pas la reveler.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.api.deps import exige_role
from app.core.roles import PEUT_ADMINISTRER
from app.pipeline.collect.telegram.mtproto_client import (
    SessionBusy,
    TelegramNotConfigured,
)
from app.services import telegram_account_service as service

router = APIRouter(
    prefix="/api/telegram",
    tags=["telegram"],
    dependencies=[Depends(exige_role(PEUT_ADMINISTRER))],
)


class LoginOut(BaseModel):
    model_config = {"extra": "forbid"}

    phase: str
    qr_svg: str | None
    qr_expires_at: datetime | None
    message: str | None
    via_tor: bool
    password_attempts_left: int

    @classmethod
    def from_snapshot(cls, s: service.LoginSnapshot) -> "LoginOut":
        return cls(
            phase=s.phase,
            qr_svg=s.qr_svg,
            qr_expires_at=s.qr_expires_at,
            message=s.message,
            via_tor=s.via_tor,
            password_attempts_left=s.password_attempts_left,
        )


class StatusOut(BaseModel):
    model_config = {"extra": "forbid"}

    api_configured: bool
    connected: bool
    authorized: bool | None
    login: LoginOut


class StartLoginIn(BaseModel):
    model_config = {"extra": "forbid"}

    sans_tor: bool = False


class PasswordIn(BaseModel):
    model_config = {"extra": "forbid"}

    password: str


@router.get("/status", response_model=StatusOut)
def status(check: bool = False) -> StatusOut:
    """`check=true` interroge Telegram pour savoir si la session est encore
    valide (quelques secondes, via Tor)."""
    s = service.account_status(check=check)
    return StatusOut(
        api_configured=s.api_configured,
        connected=s.connected,
        authorized=s.authorized,
        login=LoginOut.from_snapshot(s.login),
    )


@router.post("/login", response_model=LoginOut, status_code=202)
def start_login(payload: StartLoginIn) -> LoginOut:
    try:
        return LoginOut.from_snapshot(service.start_qr_login(sans_tor=payload.sans_tor))
    except TelegramNotConfigured as exc:
        raise HTTPException(
            status_code=400,
            detail="TELEGRAM_API_ID / TELEGRAM_API_HASH absents du fichier .env",
        ) from exc


@router.get("/login", response_model=LoginOut)
def login_state() -> LoginOut:
    return LoginOut.from_snapshot(service.current_login())


@router.post("/login/password", response_model=LoginOut)
def login_password(payload: PasswordIn) -> LoginOut:
    try:
        return LoginOut.from_snapshot(service.submit_password(payload.password))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/login/cancel", response_model=LoginOut)
def login_cancel() -> LoginOut:
    return LoginOut.from_snapshot(service.cancel_login())


@router.post("/logout", status_code=204, response_model=None)
def logout() -> Response:
    try:
        service.logout()
    except SessionBusy as exc:
        raise HTTPException(
            status_code=409,
            detail="Session occupée (connexion ou collecte en cours) : réessayer.",
        ) from exc
    return Response(status_code=204)
