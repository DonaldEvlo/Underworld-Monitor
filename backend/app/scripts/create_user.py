"""Creation de compte en ligne de commande.

Aucun endpoint d'inscription n'est expose par l'API (outil interne, pas de
self-service) -- un compte se cree via ce script ou, une fois un
administrateur en place, depuis la page Comptes. Le mot de passe est hache
(argon2) avant persistance.

Le role par defaut est `analyst` (voir core/roles.py). Le PREMIER compte d'une
installation doit etre cree en `admin`, sinon personne ne peut gerer les
comptes, les sources ni la planification.

Usage :
    docker compose exec backend python -m app.scripts.create_user <username> --role admin
"""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from datetime import datetime, timezone

from app.core.roles import DEFAULT_ROLE, Role
from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import SessionLocal
from app.repositories.user_repo import UserRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("username")
    parser.add_argument(
        "--role",
        choices=[r.value for r in Role],
        default=DEFAULT_ROLE.value,
        help=f"role du compte (defaut : {DEFAULT_ROLE.value})",
    )
    args = parser.parse_args(argv)

    password = getpass.getpass("Mot de passe : ")
    confirm = getpass.getpass("Confirmer le mot de passe : ")
    if password != confirm:
        print("Erreur : les deux mots de passe ne correspondent pas.", file=sys.stderr)
        return 1
    if len(password) < 8:
        print(
            "Erreur : le mot de passe doit faire au moins 8 caracteres.",
            file=sys.stderr,
        )
        return 1

    with SessionLocal() as db:
        repo = UserRepository(db)
        if repo.get_by_username(args.username) is not None:
            print(
                f"Erreur : un utilisateur « {args.username} » existe deja.",
                file=sys.stderr,
            )
            return 1

        repo.create(
            User(
                id=uuid.uuid4(),
                username=args.username,
                password_hash=hash_password(password),
                role=args.role,
                active=True,
                created_at=datetime.now(timezone.utc),
            )
        )

    print(f"Utilisateur « {args.username} » cree avec succes (role {args.role}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
