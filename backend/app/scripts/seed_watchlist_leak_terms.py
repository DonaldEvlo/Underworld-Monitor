"""Enrichit la watchlist avec des termes/expressions relatifs aux fuites de
donnees (FR/EN/RU), a partir d'une liste fournie par l'utilisateur couvrant :
termes generiques de fuite/vente, identifiants/comptes, donnees financieres,
secteurs sensibles, ransomware/extorsion, documents gouvernementaux,
marketplaces, et variantes obfusquees concretes (leetspeak/separateurs geres
nativement par keyword_match.py, voir ce module).

N'ajoute pas les patterns generiques abstraits ("leetspeak general",
"d a t a b a s e" comme regle) : seulement des termes concrets, le matcher
normalise (keyword_match.py) gere deja leurs variantes obfusquees
automatiquement (pas besoin de lister "d4tabase" ET "database" separement).

Usage : python -m app.scripts.seed_watchlist_leak_terms
"""

from app.db.models.keyword import Keyword
from app.db.session import SessionLocal
from app.repositories.keyword_repo import KeywordRepository

TERMS = [
    # --- 1. Termes generiques de fuite/vente de donnees ---
    # Anglais
    "leak",
    "leaked",
    "data leak",
    "database leak",
    "dump",
    "database dump",
    "full dump",
    "sql dump",
    "breach",
    "data breach",
    "breached",
    "for sale",
    "selling",
    "sale thread",
    "combo list",
    "combolist",
    "fresh leak",
    "fresh data",
    "new leak",
    "exposed",
    "exposed database",
    "stolen data",
    "stolen db",
    # Francais
    "fuite de donnees",
    "fuite de base de donnees",
    "base de donnees piratee",
    "donnees volees",
    "vente de donnees",
    "a vendre",
    "compromission",
    "piratage de base de donnees",
    # Russe
    "утечка",
    "утечка данных",
    "слив базы",
    "слив данных",
    "дамп базы данных",
    "взлом базы данных",
    "продажа базы",
    "база данных в продаже",
    "свежий слив",
    # --- 2. Identifiants et comptes ---
    "credentials",
    "creds",
    "login:pass",
    "account checker",
    "cracked accounts",
    "cookies",
    "session tokens",
    "auth tokens",
    "2fa bypass",
    "otp bypass",
    "email:pass",
    "user:pass combo",
    "identifiants voles",
    "comptes pirates",
    "аккаунты",
    "пароли",
    "куки",
    "обход 2fa",
    # --- 3. Donnees financieres ---
    "carding",
    "cvv",
    "fullz",
    "dumps track1",
    "dumps track2",
    "bank logs",
    "bank drops",
    "credit card leak",
    "cc dump",
    "crypto wallet",
    "seed phrase",
    "private key leak",
    "swift",
    "iban leak",
    "cartes bancaires",
    "fuite carte bancaire",
    "банковские логи",
    "утечка карт",
    "приватный ключ",
    # --- 4. Entreprises / secteurs sensibles ---
    "internal documents",
    "confidential",
    "source code leak",
    "github leak",
    "gitlab leak",
    "employee database",
    "hr data",
    "customer database",
    "client list",
    "vpn access",
    "rdp access",
    "remote access for sale",
    "initial access broker",
    "iab",
    "documents internes",
    "documents confidentiels",
    "base employes",
    "liste clients",
    "acces rdp",
    "внутренние документы",
    "база сотрудников",
    "доступ rdp",
    # --- 5. Ransomware / extorsion ---
    "ransomware",
    "encrypted",
    "decryptor",
    "double extortion",
    "leak site",
    "press release",
    "deadline",
    "countdown",
    "not paid",
    "published",
    "rancongiciel",
    "site de fuite",
    "non paye",
    "шифровальщик",
    "вымогатель",
    "утечка не оплачена",
    # --- 6. Documents gouvernementaux / institutionnels ---
    "gov leak",
    "government database",
    "military leak",
    "classified",
    "passport scan",
    "id scan",
    "kyc leak",
    "fuite gouvernementale",
    "documents classifies",
    "scan passeport",
    "государственная база",
    "секретные документы",
    # --- 7. Marketplaces / jargon specifique ---
    "escrow",
    "vendor",
    "verified vendor",
    "pgp key",
    "pgp verified",
    "rip report",
    "scammer list",
    "feedback",
    "vouch",
    "vendeur verifie",
    "liste arnaqueurs",
    "эскроу",
    "проверенный продавец",
    "список мошенников",
    # --- 8. Variantes concretes d'obfuscation ---
    # (formes explicitement listees par l'utilisateur -- keyword_match.py gere
    # deja automatiquement leurs variantes en plus, pas besoin d'en ajouter
    # d'autres au cas par cas)
    "l3ak",
    "d4ta",
    "hack3d",
    "d0x",
]


if __name__ == "__main__":
    db = SessionLocal()
    repo = KeywordRepository(db)

    existing_terms = {kw.term.lower() for kw in repo.list()}
    created, skipped = 0, 0

    for term in TERMS:
        if term.lower() in existing_terms:
            skipped += 1
            continue
        repo.create(Keyword(term=term, active=True))
        existing_terms.add(term.lower())
        created += 1

    print(f"{created} terme(s) ajoute(s), {skipped} deja present(s) (ignores)")
