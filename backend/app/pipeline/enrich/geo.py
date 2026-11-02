"""Pays et continent d'une organisation victime, derives de son domaine.

Sert le classement par continent et la carte des pays touches. Logique pure
(voir CONTRIBUTING.md §3.3) : aucune requete, aucun appel reseau, aucune base de
donnees GeoIP -- uniquement la structure du nom de domaine.

⚠️ COUVERTURE PARTIELLE ET ASSUMEE : environ 30 %. Mesure du 2026-09-02 --
**2165 des 3101 domaines de victimes sont des gTLD** (`.com`, `.net`, `.org`)
et ne portent AUCUNE information de pays. Ils ressortent a `None`, jamais
devines. Une carte construite ici montre donc « les pays identifiables », pas
« les pays touches » : le dire est une condition de son honnetete, sans quoi
elle sous-represente massivement les organisations mondiales et americaines,
qui utilisent `.com`.

⚠️ Ne JAMAIS combler ce trou par une resolution DNS ou un GeoIP sur l'adresse
du serveur : ce serait une requete active vers l'infrastructure de la victime
(regle 1 -- observation uniquement), et l'hebergement ne dit de toute facon
rien de la nationalite d'une organisation (un cloud irlandais heberge le monde
entier).
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# ccTLD utilises comme GENERIQUES -- ne jamais attribuer au pays qui les porte.
#
# Verifie sur le corpus reel le 2026-09-02, domaine par domaine, et non
# suppose : `.io` ne contient qu'`apollo.io`, `etherscan.io`, `cracked.io`,
# `gofile.io` -- aucun lien avec le Territoire britannique de l'ocean Indien.
# `.to` ne contient que des forums de cracking (`cracked.to`, `nulled.to`),
# aucun lien avec les Tonga. `.ly` : `bit.ly`, `sinister.ly` -- pas la Libye.
# `.me` : `telegram.me`, `wa.me`, `signal.me` -- pas le Montenegro.
#
# Les attribuer produirait une carte ou les Tonga et le Montenegro figurent
# parmi les pays les plus touches. C'est le meme piege que le comptage sature
# d'IntelX : un chiffre techniquement exact et informativement faux.
# --------------------------------------------------------------------------
_GENERIC_CCTLDS: frozenset[str] = frozenset(
    {
        "io",
        "to",
        "ly",
        "me",
        "su",
        "cc",
        "tv",
        "ai",
        "gg",
        "sh",
        "fm",
        "la",
        "ws",
        "nu",
        "st",
        "am",
        "im",
        "ms",
        "vc",
    }
)

# `.co` est le cas MIXTE, et il se tranche sur la STRUCTURE, pas sur le TLD.
#
# Mesure : `fiducie-exemple.gov.co`, `sante-exemple.gov.co`, `ecole-exemple.edu.co`,
# `deportes-exemple.com.co` sont bel et bien colombiens -- dont deux institutions
# publiques. Tandis que `rentry.co`, `ibb.co`, `decrypt.co`, `vrv.co` sont des
# services generiques. Le discriminant est le second niveau.
#
# Ecarter tout `.co` perdrait de vraies victimes colombiennes ; tout accepter
# ferait de la Colombie un faux pays majeur.
_CO_COUNTRY_SECOND_LEVELS: frozenset[str] = frozenset(
    {"com", "gov", "edu", "org", "net", "mil"}
)

# --------------------------------------------------------------------------
# ccTLD -> code pays ISO 3166-1 alpha-2.
#
# Couvre les 44 ccTLD presents dans le corpus au 2026-09-02, plus l'Afrique
# entiere : c'est le perimetre cible de la plateforme, et une carte muette sur
# l'Afrique manquerait sa raison d'etre. `uk` et `su` sont des exceptions
# historiques (le code ISO est GB, et l'URSS n'existe plus).
# --------------------------------------------------------------------------
_CCTLD_TO_COUNTRY: dict[str, str] = {
    # Afrique -- perimetre prioritaire
    "dz": "DZ",
    "ao": "AO",
    "bj": "BJ",
    "bw": "BW",
    "bf": "BF",
    "bi": "BI",
    "cm": "CM",
    "cv": "CV",
    "cf": "CF",
    "td": "TD",
    "km": "KM",
    "cd": "CD",
    "cg": "CG",
    "ci": "CI",
    "dj": "DJ",
    "eg": "EG",
    "gq": "GQ",
    "er": "ER",
    "et": "ET",
    "ga": "GA",
    "gm": "GM",
    "gh": "GH",
    "gn": "GN",
    "gw": "GW",
    "ke": "KE",
    "ls": "LS",
    "lr": "LR",
    "ly": "LY",
    "mg": "MG",
    "mw": "MW",
    "ml": "ML",
    "mr": "MR",
    "mu": "MU",
    "ma": "MA",
    "mz": "MZ",
    "na": "NA",
    "ne": "NE",
    "ng": "NG",
    "rw": "RW",
    "sn": "SN",
    "sc": "SC",
    "sl": "SL",
    "so": "SO",
    "za": "ZA",
    "ss": "SS",
    "sd": "SD",
    "sz": "SZ",
    "tz": "TZ",
    "tg": "TG",
    "tn": "TN",
    "ug": "UG",
    "zm": "ZM",
    "zw": "ZW",
    # Europe
    "al": "AL",
    "at": "AT",
    "by": "BY",
    "be": "BE",
    "ba": "BA",
    "bg": "BG",
    "hr": "HR",
    "cy": "CY",
    "cz": "CZ",
    "dk": "DK",
    "ee": "EE",
    "fi": "FI",
    "fr": "FR",
    "de": "DE",
    "gr": "GR",
    "hu": "HU",
    "is": "IS",
    "ie": "IE",
    "it": "IT",
    "lv": "LV",
    "lt": "LT",
    "lu": "LU",
    "mt": "MT",
    "md": "MD",
    "mc": "MC",
    "nl": "NL",
    "no": "NO",
    "pl": "PL",
    "pt": "PT",
    "ro": "RO",
    "ru": "RU",
    "rs": "RS",
    "sk": "SK",
    "si": "SI",
    "es": "ES",
    "se": "SE",
    "ch": "CH",
    "ua": "UA",
    "uk": "GB",
    "gb": "GB",
    # Amerique du Nord et centrale
    "us": "US",
    "ca": "CA",
    "mx": "MX",
    "cr": "CR",
    "cu": "CU",
    "do": "DO",
    "gt": "GT",
    "ht": "HT",
    "hn": "HN",
    "jm": "JM",
    "ni": "NI",
    "pa": "PA",
    "sv": "SV",
    "pr": "PR",
    "bs": "BS",
    "bb": "BB",
    "tt": "TT",
    # Amerique du Sud
    "ar": "AR",
    "bo": "BO",
    "br": "BR",
    "cl": "CL",
    "co": "CO",
    "ec": "EC",
    "gy": "GY",
    "py": "PY",
    "pe": "PE",
    "sr": "SR",
    "uy": "UY",
    "ve": "VE",
    # Asie
    "af": "AF",
    "az": "AZ",
    "bh": "BH",
    "bd": "BD",
    "bt": "BT",
    "kh": "KH",
    "cn": "CN",
    "ge": "GE",
    "hk": "HK",
    "in": "IN",
    "id": "ID",
    "ir": "IR",
    "iq": "IQ",
    "il": "IL",
    "jp": "JP",
    "jo": "JO",
    "kz": "KZ",
    "kw": "KW",
    "kg": "KG",
    "kr": "KR",
    "lb": "LB",
    "mo": "MO",
    "my": "MY",
    "mv": "MV",
    "mn": "MN",
    "mm": "MM",
    "np": "NP",
    "om": "OM",
    "pk": "PK",
    "ps": "PS",
    "ph": "PH",
    "qa": "QA",
    "sa": "SA",
    "sg": "SG",
    "lk": "LK",
    "sy": "SY",
    "tw": "TW",
    "tj": "TJ",
    "th": "TH",
    "tr": "TR",
    "tm": "TM",
    "ae": "AE",
    "uz": "UZ",
    "vn": "VN",
    "ye": "YE",
    # Oceanie
    "au": "AU",
    "fj": "FJ",
    "nz": "NZ",
    "pg": "PG",
    "sb": "SB",
    "vu": "VU",
}

_CONTINENT_BY_COUNTRY: dict[str, str] = {}


def _register(continent: str, codes: str) -> None:
    for code in codes.split():
        _CONTINENT_BY_COUNTRY[code] = continent


_register(
    "Afrique",
    "DZ AO BJ BW BF BI CM CV CF TD KM CD CG CI DJ EG GQ ER ET GA GM GH GN GW "
    "KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RW SN SC SL SO ZA SS SD SZ TZ "
    "TG TN UG ZM ZW",
)
_register(
    "Europe",
    "AL AT BY BE BA BG HR CY CZ DK EE FI FR DE GR HU IS IE IT LV LT LU MT MD "
    "MC NL NO PL PT RO RU RS SK SI ES SE CH UA GB",
)
_register("Amerique du Nord", "US CA MX CR CU DO GT HT HN JM NI PA SV PR BS BB TT")
_register("Amerique du Sud", "AR BO BR CL CO EC GY PY PE SR UY VE")
_register(
    "Asie",
    "AF AZ BH BD BT KH CN GE HK IN ID IR IQ IL JP JO KZ KW KG KR LB MO MY MV "
    "MN MM NP OM PK PS PH QA SA SG LK SY TW TJ TH TR TM AE UZ VN YE",
)
_register("Oceanie", "AU FJ NZ PG SB VU")


def country_for_domain(domain: str | None) -> str | None:
    """Code pays ISO alpha-2 deduit du domaine, ou `None` si indeterminable.

    `None` signifie « pas d'indice de pays » (un gTLD, 70 % du corpus), jamais
    « pays inconnu au sens d'introuvable ». Ne pas l'afficher comme une
    categorie de pays.
    """
    if not domain:
        return None
    labels = domain.strip().strip(".").lower().split(".")
    if len(labels) < 2:
        return None

    tld = labels[-1]
    if tld in _GENERIC_CCTLDS:
        return None

    if tld == "co":
        # Colombie seulement si le second niveau l'indique (voir
        # _CO_COUNTRY_SECOND_LEVELS) -- `rentry.co` n'est pas colombien.
        if len(labels) >= 3 and labels[-2] in _CO_COUNTRY_SECOND_LEVELS:
            return "CO"
        return None

    return _CCTLD_TO_COUNTRY.get(tld)


def continent_for_country(country_code: str | None) -> str | None:
    if not country_code:
        return None
    return _CONTINENT_BY_COUNTRY.get(country_code.upper())


def locate_domain(domain: str | None) -> tuple[str | None, str | None]:
    """(code pays, continent) pour un domaine. Les deux sont `None` ensemble
    quand le domaine ne porte aucun indice."""
    country = country_for_domain(domain)
    return country, continent_for_country(country)
