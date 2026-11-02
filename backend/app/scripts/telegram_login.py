"""Premiere connexion du compte de lecture Telegram (a lancer A LA MAIN, une fois).

    docker compose exec backend python -m app.scripts.telegram_login --qr

Demande le numero, envoie le code, DIT PAR QUEL CANAL il part, puis demande
le code (ou `r` pour le redemander par le canal suivant) et, si elle est
activee, le mot de passe de verification en deux etapes. Ecrit la session
dans `TELEGRAM_SESSION_PATH` (volume Docker, jamais le depot).

⚠️ `--qr` : CONNEXION PAR QR CODE, SANS CODE A RECEVOIR (2026-09-26). Depuis
fevrier 2023, une application tierce ne recoit son code QUE dans
l'application Telegram (plus de SMS), et de nombreux cas 2025-2026 signalent
que ce code n'arrive jamais, quels que soient l'api_id et l'IP (Telethon
#4687, #4730) -- c'est ce qui a ete constate ici, avec ET sans Tor. Le QR
code est une methode officiellement ouverte aux applications tierces
(core.telegram.org/api/auth) : le telephone deja connecte l'accepte, sans
aucun code a transmettre.

⚠️ Pourquoi pas `client.start()` : il n'indique pas OU le code est envoye.
Or Telegram l'envoie d'abord DANS L'APPLICATION (conversation « Telegram »)
des qu'une session est ouverte ailleurs, pas par SMS -- constate a l'usage :
« aucun code envoye » alors qu'il attendait dans l'application.

⚠️ La connexion passe par TOR comme la collecte (regle 3). EXCEPTION
DOCUMENTEE (decision de projet, 2026-09-26) : `--sans-tor` fait CETTE
premiere connexion depuis l'IP de l'hote (depuis un poste sous VPN). Motif
mesure : via Tor, Telegram acceptait la demande (`SentCodeTypeApp`) mais ne
remettait AUCUN code dans l'application, et le renvoi etait refuse
(`SendCodeUnavailableError`) -- filtrage anti-abus silencieux d'une connexion
Tor + application neuve. Cout OPSEC faible : Telegram connait deja l'IP du
telephone et celle de my.telegram.org. L'option ne vit QUE dans ce script :
la collecte (`mtproto_client.build_client`) reste obligatoirement sous Tor.
⚠️ Rien d'identifiant n'est affiche ni journalise : ni numero, ni nom, ni
identifiant du compte. La session VAUT le compte : ne jamais la copier hors
du volume, ne jamais la versionner.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
from typing import Any

from app.pipeline.collect.telegram.mtproto_client import (
    mark_authorized,
    session_file,
    session_lock,
)

# Meme client que la page « Compte Telegram » : `receive_updates=True`, sans
# quoi la connexion QR n'aboutit jamais (voir `build_client`).
from app.services.telegram_account_service import build_login_client

# Canal de remise du code, selon le type renvoye par Telegram.
_CANAUX = {
    "SentCodeTypeApp": (
        "dans l'APPLICATION Telegram : conversation « Telegram » (coche bleue) "
        "sur un appareil deja connecte avec ce numero -- pas par SMS"
    ),
    "SentCodeTypeSms": "par SMS",
    "SentCodeTypeFragmentSms": "par SMS (via Fragment)",
    "SentCodeTypeFirebaseSms": "par SMS",
    "SentCodeTypeCall": "par APPEL vocal",
    "SentCodeTypeFlashCall": "par appel manque (le code = fin du numero appelant)",
    "SentCodeTypeMissedCall": "par appel manque (le code = fin du numero appelant)",
    "SentCodeTypeEmailCode": "par EMAIL (adresse de connexion du compte)",
    "SentCodeTypeSetUpEmailRequired": (
        "impossible : Telegram exige d'abord une adresse email de connexion -- "
        "a configurer dans l'application (Parametres > Confidentialite)"
    ),
}


def _canal(type_: Any) -> str:
    nom = type(type_).__name__ if type_ is not None else "inconnu"
    return _CANAUX.get(nom, f"canal non reconnu ({nom})")


def _annonce(envoi: Any) -> None:
    print(f"\nCode envoye {_canal(envoi.type)}.")
    if getattr(envoi, "next_type", None) is not None:
        attente = getattr(envoi, "timeout", None)
        delai = f" apres {attente} s" if attente else ""
        print(f"  Sinon, `r` le redemande{delai} {_canal(envoi.next_type)}.")


async def _par_qr(client: Any) -> None:
    """Connexion par QR code : aucun code a recevoir.

    Le jeton expire en ~30 s (core.telegram.org/api/qr-login) : il est
    regenere et le QR reaffiche tant que personne ne l'a scanne."""
    import qrcode
    from telethon.errors import SessionPasswordNeededError

    connexion = await client.qr_login()
    print(
        "\nSur le telephone connecte au compte dedie : Parametres > Appareils >"
        " « Connecter un appareil » (Link Desktop Device), puis scanner :\n"
    )
    while True:
        qr = qrcode.QRCode(border=1)
        qr.add_data(connexion.url)
        qr.print_ascii(invert=True)
        try:
            await connexion.wait(timeout=25)
            return
        except asyncio.TimeoutError:
            print("\nQR expire, nouveau QR :\n")
            await connexion.recreate()
        except SessionPasswordNeededError:
            await client.sign_in(
                password=getpass.getpass(
                    "Mot de passe (verification en deux etapes) : "
                )
            )
            return


async def _par_code(client: Any) -> None:
    from telethon.errors import (
        FloodWaitError,
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        SessionPasswordNeededError,
    )
    from telethon.tl.functions.auth import ResendCodeRequest

    numero = input("Numero (format international, ex. +221...) : ").strip()
    try:
        envoi = await client.send_code_request(numero)
    except FloodWaitError as exc:
        print(f"Trop de demandes : Telegram impose d'attendre {exc.seconds} s.")
        return
    _annonce(envoi)

    while True:
        saisie = input("Code (ou `r` pour le redemander) : ").strip()
        if saisie.lower() == "r":
            try:
                envoi = await client(ResendCodeRequest(numero, envoi.phone_code_hash))
            except Exception as exc:  # noqa: BLE001
                print(f"Renvoi refuse : {type(exc).__name__} -- {exc}")
                continue
            _annonce(envoi)
            continue
        try:
            await client.sign_in(
                phone=numero, code=saisie, phone_code_hash=envoi.phone_code_hash
            )
            return
        except PhoneCodeInvalidError:
            print("Code incorrect, reessayer.")
        except PhoneCodeExpiredError:
            print("Code expire : taper `r` pour en recevoir un nouveau.")
        except SessionPasswordNeededError:
            await client.sign_in(
                password=getpass.getpass(
                    "Mot de passe (verification en deux etapes) : "
                )
            )
            return


async def _connexion(sans_tor: bool, par_qr: bool) -> None:
    if sans_tor:
        print(
            "ATTENTION : connexion SANS Tor, depuis l'IP de cette machine "
            "(premiere connexion uniquement ; la collecte reste sous Tor)."
        )
    client = build_login_client(sans_tor)
    await client.connect()
    try:
        if await client.is_user_authorized():
            print(f"Deja connecte. Session : {session_file()}")
            return
        await (_par_qr(client) if par_qr else _par_code(client))
        if await client.is_user_authorized():
            mark_authorized(True)
            print(f"\nSession enregistree : {session_file()}")
        else:
            print("\nConnexion non aboutie.")
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Premiere connexion Telegram")
    parser.add_argument(
        "--sans-tor",
        action="store_true",
        help="premiere connexion depuis l'IP de l'hote (exception documentee)",
    )
    parser.add_argument(
        "--qr",
        action="store_true",
        help="connexion par QR code, scanne depuis le telephone (aucun code)",
    )
    args = parser.parse_args()
    with session_lock():
        asyncio.run(_connexion(args.sans_tor, args.qr))


if __name__ == "__main__":
    main()
