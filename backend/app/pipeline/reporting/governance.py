"""Vue de gouvernance (RSSI / direction) : ce que le service a produit, et la
menace sectorielle du perimetre surveille.

⚠️ AGREGATS UNIQUEMENT, par conception et non par oubli : le profil `viewer`
(RSSI) « ne consulte pas le detail des contenus » (dossier de conception,
core/roles.py). Aucun nom de victime, aucune valeur, aucun `.onion` ne sort de
ce module -- seulement des comptes par gravite, statut, secteur, pays, gang.

Deux blocs, deux sources, et il ne faut pas les confondre :

- ACTIVITE DU SERVICE (`service_activity`) : nos alertes. Corpus JEUNE --
  premieres alertes le 2026-09-15, et la premiere semaine est un RATTRAPAGE
  historique (sources collectees pour la premiere fois), pas une tendance.
  Les delais de prise en charge et de resolution restent « non mesurables »
  tant qu'aucune alerte n'a ete traitee : une moyenne sur zero cas n'existe
  pas, on ne l'invente pas (meme doctrine que `None` = « pas de mesure »).

- MENACE SECTORIELLE (`sector_threat`) : victimes publiees par les gangs sur
  12 mois, d'apres les historiques ransomware.live DEJA en cache (aucun appel
  reseau). ⚠️ La couverture depend des gangs presents dans le cache : elle est
  RENDUE avec les chiffres (nombre de gangs), sans quoi un cache partiel se
  lirait comme une baisse de la menace. Le pays et le secteur sont DECLARES
  par le tiers, jamais mesures.

Logique pure : aucune base, aucun reseau.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median

from app.pipeline.alerting.rules import CRITICAL_SECTORS

SEVERITES = ("critical", "high", "medium", "low")

#: Libelles francais des 14 valeurs `activity` de ransomware.live (releve
#: exhaustif du cache, 2026-09-30). Une valeur inconnue garde son libelle
#: d'origine : mieux vaut un mot anglais qu'un secteur qui disparait.
SECTEURS_FR = {
    "Manufacturing": "Industrie manufacturière",
    "Professional Services": "Services aux entreprises",
    "Technology": "Technologies",
    "Healthcare": "Santé",
    "Retail & E-Commerce": "Commerce et e-commerce",
    "Financial Services": "Services financiers",
    "Transportation": "Transport",
    "Agriculture and Food Production": "Agriculture et agroalimentaire",
    "Education": "Éducation",
    "Government & Defense": "Administration et défense",
    "Energy & Utilities": "Énergie et services collectifs",
    "Hospitality": "Hôtellerie et tourisme",
    "non renseigne": "non renseigné",
    "autres": "autres",
}
# Au-dela, le reste est regroupe : un classement de 40 lignes ne se lit pas.
TOP = 8


@dataclass(frozen=True)
class AlertFact:
    """Une alerte, reduite a ce qu'un tableau de gouvernance peut montrer."""

    alert_date: date
    created_at: datetime
    severity: str
    status: str
    sector: str | None = None
    country: str | None = None
    gang: str | None = None
    credibility: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None


@dataclass(frozen=True)
class VictimFact:
    """Une victime publiee par un gang, d'apres un tiers -- SANS son nom."""

    discovered: datetime
    gang: str
    sector: str | None = None
    country: str | None = None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _lundi(jour: date) -> date:
    return jour - timedelta(days=jour.weekday())


def _classement(compteur: Counter, top: int = TOP) -> list[dict]:
    lignes = [{"label": k, "count": n} for k, n in compteur.most_common(top)]
    reste = sum(compteur.values()) - sum(ligne["count"] for ligne in lignes)
    if reste:
        lignes.append({"label": "autres", "count": reste})
    return lignes


def _secteurs(compteur: Counter) -> list[dict]:
    """Secteurs avec le drapeau NIS2 (annexe I, voir rules.CRITICAL_SECTORS).
    « non renseigne » reste visible : le cacher gonflerait les autres parts."""
    return [
        {
            "label": ligne["label"],
            "label_fr": SECTEURS_FR.get(ligne["label"], ligne["label"]),
            "count": ligne["count"],
            "critical": ligne["label"] in CRITICAL_SECTORS,
        }
        for ligne in _classement(compteur, top=12)
    ]


def _delai_median_heures(debuts_fins: list[tuple[datetime, datetime]]) -> float | None:
    """Mediane en heures, ou None s'il n'y a AUCUN cas mesure."""
    durees = [
        (_aware(fin) - _aware(debut)).total_seconds() / 3600
        for debut, fin in debuts_fins
        if fin >= debut
    ]
    return round(median(durees), 1) if durees else None


def service_activity(alertes: list[AlertFact]) -> dict:
    """Ce que le service a produit, et comment il a ete traite."""
    par_semaine: dict[date, Counter] = defaultdict(Counter)
    for a in alertes:
        par_semaine[_lundi(a.alert_date)][a.severity] += 1
    semaines = [
        {"week": lundi.isoformat(), **{s: par_semaine[lundi][s] for s in SEVERITES}}
        for lundi in sorted(par_semaine)
    ]

    acquittements = [
        (a.created_at, a.acknowledged_at) for a in alertes if a.acknowledged_at
    ]
    resolutions = [(a.created_at, a.resolved_at) for a in alertes if a.resolved_at]
    resolues = [a for a in alertes if a.status == "resolved" or a.resolved_at]
    faux_positifs = sum(1 for a in resolues if a.resolution_reason == "false_positive")

    return {
        "total": len(alertes),
        "first_alert_date": min((a.alert_date for a in alertes), default=None),
        "last_alert_date": max((a.alert_date for a in alertes), default=None),
        "by_severity": {
            s: sum(1 for a in alertes if a.severity == s) for s in SEVERITES
        },
        "by_status": dict(Counter(a.status for a in alertes)),
        "weekly": semaines,
        "by_sector": _secteurs(Counter(a.sector or "non renseigne" for a in alertes)),
        "by_country": _classement(
            Counter(a.country or "non renseigné" for a in alertes)
        ),
        "by_gang": _classement(Counter(a.gang for a in alertes if a.gang)),
        "by_credibility": dict(
            Counter(a.credibility or "non évaluée" for a in alertes)
        ),
        # None = AUCUN cas : jamais 0, qui dirait « traite instantanement ».
        "median_hours_to_acknowledge": _delai_median_heures(acquittements),
        "median_hours_to_resolve": _delai_median_heures(resolutions),
        "treated": len(acquittements)
        + sum(1 for a in resolues if not a.acknowledged_at),
        "false_positive_rate": (
            round(faux_positifs / len(resolues), 3) if resolues else None
        ),
    }


def world_threat(
    victimes: list[VictimFact],
    *,
    continent_de,
    continents_mis_en_avant: tuple[str, ...],
    now: datetime,
    months: int = 12,
) -> dict:
    """La menace MONDIALE sur `months` mois, par continent, avec les continents
    surveillés SIGNALÉS mais jamais isolés.

    ⚠️ Répond à une objection de fond (2026-10-03) : dans le cyberespace il n'y
    a pas de frontière, et ne montrer que l'Afrique laissait croire à une
    plateforme régionale. La collecte et la notation sont mondiales ; seul le
    cas d'étude est africain. On met donc l'Afrique EN AVANT, dans le contexte
    du reste du monde, pas à sa place.

    Une victime sans pays déclaré est comptée à part (« non renseigné ») et
    jamais rattachée à un continent par défaut."""
    now = _aware(now)
    debut = _debut_fenetre(now, months)
    retenues = [v for v in victimes if debut <= _aware(v.discovered) <= now]
    total = len(retenues)
    par_continent: dict[str, list[VictimFact]] = {}
    for v in retenues:
        continent = continent_de((v.country or "").upper()) or "non renseigné"
        par_continent.setdefault(continent, []).append(v)
    lignes = []
    for continent, vs in sorted(par_continent.items(), key=lambda kv: -len(kv[1])):
        critiques = sum(1 for v in vs if (v.sector or "") in CRITICAL_SECTORS)
        lignes.append(
            {
                "label": continent,
                "count": len(vs),
                "share": round(len(vs) / total, 3) if total else None,
                "critical_sector_share": round(critiques / len(vs), 3),
                "highlighted": continent in continents_mis_en_avant,
            }
        )
    critiques = sum(1 for v in retenues if (v.sector or "") in CRITICAL_SECTORS)
    return {
        "window_start": debut.date().isoformat(),
        "total": total,
        "critical_sector_share": round(critiques / total, 3) if total else None,
        "highlighted": list(continents_mis_en_avant),
        "by_continent": lignes,
    }


def _debut_fenetre(now: datetime, months: int) -> datetime:
    """Premier jour du mois le plus ancien d'une fenêtre de `months` mois."""
    annee, mois = now.year, now.month - (months - 1)
    while mois <= 0:
        annee, mois = annee - 1, mois + 12
    return datetime(annee, mois, 1, tzinfo=timezone.utc)


def sector_threat(
    victimes: list[VictimFact],
    *,
    continent_de,
    continents: tuple[str, ...],
    now: datetime,
    months: int = 12,
) -> dict:
    """Victimes publiees dans le perimetre sur `months` mois, par mois, secteur,
    pays et gang. `continent_de(code_pays)` vient de enrich/geo (injecte : ce
    module reste pur)."""
    now = _aware(now)
    debut = _debut_fenetre(now, months)
    cles_mois = []
    a, m = debut.year, debut.month
    for _ in range(months):
        cles_mois.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)

    retenues = [
        v
        for v in victimes
        if debut <= _aware(v.discovered) <= now
        and continent_de((v.country or "").upper()) in continents
    ]
    par_mois: dict[str, Counter] = {k: Counter() for k in cles_mois}
    for v in retenues:
        cle = _aware(v.discovered).strftime("%Y-%m")
        if cle in par_mois:
            critique = (v.sector or "") in CRITICAL_SECTORS
            par_mois[cle]["critical_sector" if critique else "other"] += 1
    total = len(retenues)
    critiques = sum(1 for v in retenues if (v.sector or "") in CRITICAL_SECTORS)
    return {
        "continents": list(continents),
        "window_start": debut.date().isoformat(),
        "total": total,
        "critical_sector_share": round(critiques / total, 3) if total else None,
        # Mois a zero GARDES : un trou dans la serie se lirait comme une donnee.
        "monthly": [
            {
                "month": k,
                "critical_sector": par_mois[k]["critical_sector"],
                "other": par_mois[k]["other"],
            }
            for k in cles_mois
        ],
        "by_sector": _secteurs(
            Counter(
                (
                    v.sector
                    if v.sector and v.sector not in ("Not Found", "Other")
                    else "non renseigne"
                )
                for v in retenues
            )
        ),
        "by_country": _classement(
            Counter((v.country or "?").upper() for v in retenues)
        ),
        "by_gang": _classement(Counter(v.gang for v in retenues)),
    }
