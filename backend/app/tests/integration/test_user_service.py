"""Tests de la gestion des comptes.

⚠️ Les tests qui comptent ici sont ceux du VERROUILLAGE. Ce service peut
rendre la configuration definitivement inaccessible par l'interface : retirer
le dernier `admin`, ou le desactiver, obligerait a repasser par la base. Les
garde-fous ne sont pas du confort, ils sont la fonction."""

from __future__ import annotations

import uuid

import pytest

from app.core.roles import Role
from app.db.models.user import User
from app.db.session import SessionLocal
from app.services import user_service

MDP = "MotDePasseAssezLong2026"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def comptes(db):
    """Cree un jeu de comptes isole, et le retire ensuite.

    ⚠️ Prefixe unique : ces tests touchent la VRAIE base (comme le reste des
    tests d'integration du projet). Un nom fixe entrerait en collision avec le
    compte reel de l'administrateur."""
    prefixe = f"t_{uuid.uuid4().hex[:8]}_"
    crees: list[User] = []

    def creer(suffixe: str, role: str) -> User:
        u = user_service.creer(db, username=prefixe + suffixe, password=MDP, role=role)
        crees.append(u)
        return u

    yield creer
    for u in crees:
        db.query(User).filter(User.id == u.id).delete()
    db.commit()


class TestCreation:
    def test_cree_un_compte_analyste_par_defaut(self, db, comptes):
        u = user_service.creer(db, username=f"t_{uuid.uuid4().hex[:8]}", password=MDP)
        try:
            assert u.role == Role.ANALYST.value
            assert u.active is True
        finally:
            db.query(User).filter(User.id == u.id).delete()
            db.commit()

    def test_role_inconnu_ne_donne_JAMAIS_l_administration(self, db, comptes):
        """⚠️ Une faute de frappe dans le role ne doit pas ouvrir la
        configuration. `role_de` ramene l'inconnu a `viewer`."""
        u = comptes("bidule", "superadmin")
        assert u.role == Role.VIEWER.value

    def test_identifiant_deja_pris_refuse(self, db, comptes):
        u = comptes("doublon", Role.ANALYST.value)
        with pytest.raises(user_service.UserServiceError, match="existe deja"):
            user_service.creer(db, username=u.username, password=MDP)

    def test_mot_de_passe_trop_court_refuse(self, db):
        with pytest.raises(user_service.UserServiceError, match="12 caracteres"):
            user_service.creer(db, username="t_court", password="court")

    def test_le_hachage_n_est_pas_le_clair(self, db, comptes):
        u = comptes("hash", Role.ANALYST.value)
        assert MDP not in u.password_hash
        assert u.password_hash.startswith("$argon2")


class TestVerrouillage:
    """⚠️ LE CŒUR DU SERVICE. Sans ces gardes, une seule manipulation rend la
    plateforme inadministrable autrement qu'en base."""

    def test_on_ne_retire_pas_le_role_du_DERNIER_admin(self, db, comptes, monkeypatch):
        """⚠️ PREMIERE VERSION CONDITIONNELLE, DONC INUTILE : elle testait la
        garde « seulement s'il n'y a aucun autre admin » -- or le compte reel
        de l'administrateur existe, si bien que la branche importante n'etait JAMAIS
        exercee et le test passait vert sans rien verifier.

        On force donc le decompte a zero plutot que de desactiver un vrai
        compte administrateur, ce qui serait destructeur."""
        temoin = comptes("adm", Role.ADMIN.value)
        monkeypatch.setattr(user_service, "_admins_actifs", lambda *a, **k: 0)
        with pytest.raises(user_service.UserServiceError, match="dernier"):
            user_service.changer_role(db, temoin, Role.ANALYST.value, demandeur=temoin)
        assert temoin.role == Role.ADMIN.value

    def test_on_ne_desactive_pas_le_DERNIER_admin(self, db, comptes, monkeypatch):
        temoin = comptes("adm2", Role.ADMIN.value)
        autre = comptes("adm3", Role.ADMIN.value)
        monkeypatch.setattr(user_service, "_admins_actifs", lambda *a, **k: 0)
        with pytest.raises(user_service.UserServiceError, match="dernier"):
            user_service.changer_activation(db, temoin, False, demandeur=autre)
        assert temoin.active is True

    def test_on_ne_supprime_pas_le_DERNIER_admin(self, db, comptes, monkeypatch):
        temoin = comptes("adm4", Role.ADMIN.value)
        autre = comptes("adm5", Role.ADMIN.value)
        monkeypatch.setattr(user_service, "_admins_actifs", lambda *a, **k: 0)
        with pytest.raises(user_service.UserServiceError, match="dernier"):
            user_service.supprimer(db, temoin, demandeur=autre)

    def test_TEMOIN_avec_un_autre_admin_la_retrogradation_est_permise(
        self, db, comptes
    ):
        """Temoin : la garde ne bloque pas tout, elle bloque le DERNIER."""
        temoin = comptes("adm6", Role.ADMIN.value)
        comptes("adm7", Role.ADMIN.value)
        user_service.changer_role(db, temoin, Role.ANALYST.value, demandeur=temoin)
        assert temoin.role == Role.ANALYST.value

    def test_on_ne_desactive_pas_son_PROPRE_compte(self, db, comptes):
        moi = comptes("moi", Role.ADMIN.value)
        with pytest.raises(user_service.UserServiceError, match="propre compte"):
            user_service.changer_activation(db, moi, False, demandeur=moi)

    def test_on_ne_supprime_pas_son_PROPRE_compte(self, db, comptes):
        moi = comptes("suppr", Role.ADMIN.value)
        with pytest.raises(user_service.UserServiceError, match="propre compte"):
            user_service.supprimer(db, moi, demandeur=moi)


class TestModifications:
    def test_changer_de_role(self, db, comptes):
        u = comptes("role", Role.ANALYST.value)
        autre = comptes("autre", Role.ADMIN.value)
        user_service.changer_role(db, u, Role.VIEWER.value, demandeur=autre)
        assert u.role == Role.VIEWER.value

    def test_desactiver_puis_reactiver(self, db, comptes):
        u = comptes("actif", Role.ANALYST.value)
        autre = comptes("autre2", Role.ADMIN.value)
        user_service.changer_activation(db, u, False, demandeur=autre)
        assert u.active is False
        user_service.changer_activation(db, u, True, demandeur=autre)
        assert u.active is True

    def test_changer_le_mot_de_passe_modifie_le_hachage(self, db, comptes):
        u = comptes("mdp", Role.ANALYST.value)
        avant = u.password_hash
        user_service.changer_mot_de_passe(db, u, "UnAutreMotDePasse2026")
        assert u.password_hash != avant

    def test_mot_de_passe_trop_court_refuse_aussi_en_modification(self, db, comptes):
        u = comptes("mdp2", Role.ANALYST.value)
        with pytest.raises(user_service.UserServiceError):
            user_service.changer_mot_de_passe(db, u, "court")


class TestAucunSecretEnSortie:
    """⚠️ FRONTIERE : le hachage du mot de passe ne doit JAMAIS sortir de
    l'API. Renvoyer le modele tel quel l'exposerait a l'interface, donc au
    journal du navigateur et a toute capture d'ecran."""

    def test_le_contrat_de_sortie_ne_porte_pas_le_hachage(self):
        from app.api.routers.users import UserOut

        assert "password_hash" not in UserOut.model_fields
        assert set(UserOut.model_fields) == {
            "id",
            "username",
            "role",
            "active",
            "created_at",
        }

    def test_un_champ_ajoute_au_modele_ne_fuit_pas(self, db, comptes):
        """`from_model` recopie champ par champ, jamais `model_validate(u)` :
        un futur champ sensible sur `User` ne partirait pas tout seul."""
        from app.api.routers.users import UserOut

        u = comptes("sortie", Role.ANALYST.value)
        serialise = UserOut.from_model(u).model_dump_json()
        assert u.password_hash not in serialise
        assert "argon2" not in serialise
