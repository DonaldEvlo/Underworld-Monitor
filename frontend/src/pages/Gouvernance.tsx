import { useEffect, useMemo, useRef, useState } from "react";

import {
  statsApi,
  type GovernanceRank,
  type GovernanceResponse,
  type GovernanceSector,
} from "../api/stats";
import { AppLayout } from "../components/layout/AppLayout";
import { BoutonExport } from "../components/ui/BoutonExport";
import { dateHeure } from "../lib/format";

/**
 * Vue de gouvernance — le poste du RSSI / de la direction.
 *
 * ⚠️ AGRÉGATS UNIQUEMENT : le profil RSSI « ne consulte pas le détail des
 * contenus » (dossier de conception). L'API ne renvoie que des comptes — aucun
 * nom de victime, aucune valeur — et cette page n'en affiche aucun.
 *
 * ⚠️ HONNÊTETÉ DES CHIFFRES : une mesure absente s'affiche « non mesurable »,
 * jamais 0 ; la menace sectorielle porte sa couverture et sa date ; un encadré
 * « Limites de lecture » reste toujours visible. Sans lui, la première semaine
 * (un rattrapage historique) se lirait comme un pic, et un cache partiel comme
 * une baisse de la menace.
 */

const MOIS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

function moisCourant(): string {
  const d = new Date();
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function moisPrecedent(mois: string): string {
  const [a, m] = mois.split("-").map(Number);
  return m === 1 ? `${a - 1}-12` : `${a}-${String(m - 1).padStart(2, "0")}`;
}

function libelleMois(mois: string): string {
  const [a, m] = mois.split("-");
  return `${MOIS_FR[Number(m) - 1] ?? m} ${a}`;
}

/** Les 12 derniers mois, du plus récent au plus ancien. */
function derniersMois(n = 12): string[] {
  const d = new Date();
  const liste: string[] = [];
  for (let i = 0; i < n; i += 1) {
    const x = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - i, 1));
    liste.push(`${x.getUTCFullYear()}-${String(x.getUTCMonth() + 1).padStart(2, "0")}`);
  }
  return liste;
}

// Noms de pays GÉNÉRÉS par le navigateur (ICU), jamais tapés de mémoire : un
// nom faux colorerait la mauvaise lecture sans qu'aucun test ne le voie.
const NOMS_PAYS = (() => {
  try {
    return new Intl.DisplayNames(["fr"], { type: "region" });
  } catch {
    return null;
  }
})();

function nomPays(code: string): string {
  if (!/^[A-Z]{2}$/.test(code) || !NOMS_PAYS) return code;
  try {
    return NOMS_PAYS.of(code) ?? code;
  } catch {
    return code;
  }
}

function heures(valeur: number | null): string {
  if (valeur === null) return "non mesurable";
  return valeur >= 1 ? `${Math.round(valeur)} h` : `${Math.round(valeur * 60)} min`;
}

export function Gouvernance() {
  const [mois, setMois] = useState<string>(moisCourant());
  const [donnees, setDonnees] = useState<GovernanceResponse | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // Mois en cours encore vide (début de mois) : on bascule UNE fois sur le
  // mois précédent et on le DIT. Sans cela, le RSSI était accueilli par une
  // page de zéros le 1er du mois (constaté à l'image le 2026-10-01).
  const [basculeDepuis, setBasculeDepuis] = useState<string | null>(null);
  const dejaBascule = useRef(false);

  useEffect(() => {
    let vivant = true;
    statsApi
      .governance(mois)
      .then((g) => {
        if (!vivant) return;
        if (g.service.total === 0 && mois === moisCourant() && !dejaBascule.current) {
          dejaBascule.current = true;
          setBasculeDepuis(mois);
          setMois(moisPrecedent(mois));
          return;
        }
        setDonnees(g);
        setErreur(null)
      })
      .catch((err) => {
        if (vivant) setErreur(err instanceof Error ? err.message : "Erreur inconnue");
      });
    return () => {
      vivant = false;
    };
  }, [mois]);

  const choixMois = useMemo(() => derniersMois(), []);

  return (
    <AppLayout title="Gouvernance">
      <div className="flex flex-col gap-4">
        <section className="pulse-panel flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <h1 className="font-display text-18 font-bold tracking-tight text-ink">
              Vue de direction
            </h1>
            <p className="mt-0.5 font-mono-label text-10.5 text-ink-dim">
              agrégats uniquement · aucune donnée de victime
              {donnees ? ` · calculé le ${dateHeure(donnees.computed_at)}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="font-mono-label text-10.5 text-ink-dim" htmlFor="mois">
              mois
            </label>
            <select
              id="mois"
              value={mois}
              onChange={(e) => {
                dejaBascule.current = true;
                setBasculeDepuis(null);
                setMois(e.target.value);
              }}
              className="rounded-md border border-line bg-panel-sunken px-2 py-1 text-body-sm text-ink"
            >
              {choixMois.map((m) => (
                <option key={m} value={m}>
                  {libelleMois(m)}
                </option>
              ))}
            </select>
            <BoutonExport
              chemin={`/api/stats/governance/report.pdf?month=${mois}`}
              nom={`rapport-direction-${mois}.pdf`}
              libelle="Rapport mensuel (PDF)"
              titre="Rapport de direction du mois, agrégats uniquement, TLP:AMBER+STRICT"
            />
          </div>
        </section>

        {basculeDepuis ? (
          <p className="pulse-panel p-3 font-mono-label text-10.5 text-ink-dim">
            {libelleMois(basculeDepuis)} ne compte encore aucune alerte : affichage de{" "}
            {libelleMois(mois)}.
          </p>
        ) : null}

        {erreur ? (
          <p className="pulse-panel p-4 text-body-sm text-critical">{erreur}</p>
        ) : null}

        {donnees ? <Contenu donnees={donnees} mois={mois} /> : null}
      </div>
    </AppLayout>
  );
}

function Contenu({ donnees, mois }: { donnees: GovernanceResponse; mois: string }) {
  const s = donnees.service;
  const m = donnees.sector_threat;
  const perimetre = m.continents.join(", ") || "non défini";
  return (
    <>
      {/* ---- Activité du service ---- */}
      <section className="pulse-panel p-4">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">
          Activité du service — {libelleMois(mois)}
        </h2>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Chiffre label="Alertes émises" valeur={`${s.total}`} />
          <Chiffre label="Critiques" valeur={`${s.by_severity.critical}`} ton="critical" />
          <Chiffre label="Élevées" valeur={`${s.by_severity.high}`} ton="warn" />
          <Chiffre label="Moyennes" valeur={`${s.by_severity.medium}`} />
        </div>
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Chiffre
            label="Délai médian de prise en charge"
            valeur={heures(s.median_hours_to_acknowledge)}
            note={s.median_hours_to_acknowledge === null ? "aucune alerte acquittée" : undefined}
          />
          <Chiffre
            label="Délai médian de résolution"
            valeur={heures(s.median_hours_to_resolve)}
            note={s.median_hours_to_resolve === null ? "aucune alerte résolue" : undefined}
          />
          <Chiffre
            label="Part de faux positifs"
            valeur={
              s.false_positive_rate === null
                ? "non mesurable"
                : `${Math.round(s.false_positive_rate * 100)} %`
            }
            note={s.false_positive_rate === null ? "parmi les alertes résolues" : undefined}
          />
        </div>

        {s.weekly.length > 0 ? (
          <div className="mt-4">
            <p className="font-mono-label text-10.5 text-ink-dim">alertes par semaine</p>
            <Semaines semaines={s.weekly} />
          </div>
        ) : null}

        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Classement titre="Secteurs touchés" lignes={s.by_sector} />
          <Classement titre="Pays" lignes={s.by_country} pays />
          <Classement titre="Groupes attaquants" lignes={s.by_gang} />
        </div>
      </section>

      {/* ---- Menace mondiale : le contexte, avant le zoom régional ---- */}
      <MenaceMondiale monde={donnees.world_threat} />

      {/* ---- Zoom sur le périmètre surveillé ---- */}
      <section className="pulse-panel p-4">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">
          Zoom sur le périmètre surveillé — {perimetre}, 12 derniers mois
        </h2>
        <p className="mt-1 font-mono-label text-10.5 text-ink-dim">
          victimes publiées par les groupes de rançongiciel · source ransomware.live ·{" "}
          {m.coverage_gangs} groupe(s) couvert(s) · pays et secteur déclarés par le tiers
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Chiffre label="Victimes sur 12 mois" valeur={`${m.total}`} />
          <Chiffre
            label="Dans un secteur critique (NIS2)"
            valeur={
              m.critical_sector_share === null
                ? "non mesurable"
                : `${Math.round(m.critical_sector_share * 100)} %`
            }
            ton="warn"
          />
          <Chiffre label="Groupes couverts" valeur={`${m.coverage_gangs}`} />
        </div>
        <div className="mt-4">
          <p className="font-mono-label text-10.5 text-ink-dim">
            victimes par mois — <span className="text-warn">secteurs critiques</span> / autres
          </p>
          <Mois mois={m.monthly} />
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Classement titre="Secteurs les plus touchés" lignes={m.by_sector} />
          <Classement titre="Pays" lignes={m.by_country} pays />
          <Classement titre="Groupes les plus actifs" lignes={m.by_gang} />
        </div>
      </section>

      {/* ---- Limites : TOUJOURS visibles ---- */}
      <section className="pulse-panel border-warn/30 p-4">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">
          Limites de lecture
        </h2>
        <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-body-sm text-ink">
          <li>
            Corpus d&apos;alertes jeune : premières alertes le{" "}
            {donnees.corpus_first_alert_date ?? "—"} ; la
            première semaine est un rattrapage historique, pas un pic.
          </li>
          <li>
            La menace sectorielle ne couvre que les {m.coverage_gangs} groupe(s) présents dans le
            cache au moment du calcul : un chiffre plus bas peut traduire une couverture partielle,
            pas une baisse de la menace.
          </li>
          <li>
            Une revendication est une déclaration de l&apos;attaquant : la plateforme lit, elle ne
            télécharge ni ne vérifie le contenu des fuites.
          </li>
          <li>
            Les délais ne se calculent qu&apos;à partir d&apos;alertes réellement acquittées ou
            résolues par un analyste.
          </li>
        </ul>
      </section>
    </>
  );
}

// Les libellés de `enrich/geo` sont des clés sans accents (partagées avec la
// cartographie) : on les accentue à l'affichage seulement.
const CONTINENTS_FR: Record<string, string> = {
  "Amerique du Nord": "Amérique du Nord",
  "Amerique du Sud": "Amérique du Sud",
  Oceanie: "Océanie",
};

/** La menace mondiale, continent par continent.
 *
 * ⚠️ Le cyberespace n'a pas de frontière : la plateforme collecte et note
 * partout, seul le cas d'étude est régional. Le continent surveillé est donc
 * MIS EN AVANT dans le contexte mondial, jamais montré seul (objection reçue
 * le 2026-10-03). */
function MenaceMondiale({ monde }: { monde: GovernanceResponse["world_threat"] }) {
  const max = Math.max(1, ...monde.by_continent.map((c) => c.count));
  const mis_en_avant = monde.by_continent.filter((c) => c.highlighted);
  const partMisEnAvant = mis_en_avant.reduce((total, c) => total + (c.share ?? 0), 0);
  return (
    <section className="pulse-panel p-4">
      <h2 className="font-display text-15 font-bold tracking-tight text-ink">
        Menace mondiale — 12 derniers mois
      </h2>
      <p className="mt-1 font-mono-label text-10.5 text-ink-dim">
        victimes publiées par les groupes de rançongiciel, tous pays · source ransomware.live ·{" "}
        {monde.coverage_gangs} groupe(s) couvert(s)
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Chiffre label="Victimes dans le monde" valeur={`${monde.total}`} />
        <Chiffre
          label="Dans un secteur critique (NIS2)"
          valeur={
            monde.critical_sector_share === null
              ? "non mesurable"
              : `${Math.round(monde.critical_sector_share * 100)} %`
          }
          ton="warn"
        />
        <Chiffre
          label={`Part du périmètre surveillé (${monde.highlighted.join(", ") || "aucun"})`}
          valeur={monde.total ? `${Math.round(partMisEnAvant * 100)} %` : "—"}
        />
      </div>
      <ul className="mt-4 flex flex-col gap-1.5">
        {monde.by_continent.map((c) => (
          <li key={c.label} className="text-body-sm text-ink">
            <div className="flex items-baseline justify-between gap-2">
              <span className={c.highlighted ? "font-semibold text-ink" : "text-ink-dim"}>
                {CONTINENTS_FR[c.label] ?? c.label}
                {c.highlighted ? (
                  <span className="ml-1.5 rounded bg-signal/[0.12] px-1 font-mono-label text-9.5 text-signal">
                    périmètre surveillé
                  </span>
                ) : null}
              </span>
              <span className="font-mono-data text-12 text-ink-dim">
                {c.count} · {Math.round(c.critical_sector_share * 100)} % NIS2
              </span>
            </div>
            <div className="mt-0.5 h-1.5 rounded bg-panel-sunken">
              <div
                className={`h-1.5 rounded ${c.highlighted ? "bg-signal" : "bg-ink-faint/60"}`}
                style={{ width: `${Math.max(2, (c.count / max) * 100)}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Chiffre({
  label,
  valeur,
  note,
  ton,
}: {
  label: string;
  valeur: string;
  note?: string;
  ton?: "critical" | "warn";
}) {
  const couleur =
    ton === "critical" ? "text-critical" : ton === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="rounded-xl border border-line bg-panel-sunken p-3">
      <p className="font-mono-label text-10.5 text-ink-dim">{label}</p>
      <p className={`mt-1 font-display text-20 font-bold ${couleur}`}>{valeur}</p>
      {note ? <p className="font-mono-label text-10 text-ink-faint">{note}</p> : null}
    </div>
  );
}

function Classement({
  titre,
  lignes,
  pays = false,
}: {
  titre: string;
  lignes: (GovernanceRank | GovernanceSector)[];
  pays?: boolean;
}) {
  const max = Math.max(1, ...lignes.map((l) => l.count));
  return (
    <div>
      <p className="font-mono-label text-10.5 text-ink-dim">{titre}</p>
      {lignes.length === 0 ? (
        <p className="mt-1 text-body-sm text-ink-faint">aucune donnée</p>
      ) : (
        <ul className="mt-1 flex flex-col gap-1">
          {lignes.map((l) => {
            const secteur = "label_fr" in l ? l : null;
            const libelle = secteur ? secteur.label_fr : pays ? nomPays(l.label) : l.label;
            return (
              <li key={l.label} className="text-body-sm text-ink">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate" title={libelle}>
                    {libelle}
                    {secteur?.critical ? (
                      <span className="ml-1.5 rounded bg-warn/[0.12] px-1 font-mono-label text-9.5 text-warn">
                        NIS2
                      </span>
                    ) : null}
                  </span>
                  <span className="font-mono-data text-12 text-ink-dim">{l.count}</span>
                </div>
                <div className="mt-0.5 h-1.5 rounded bg-panel-sunken">
                  <div
                    className={`h-1.5 rounded ${secteur?.critical ? "bg-warn" : "bg-signal"}`}
                    // Plancher : une valeur non nulle doit rester visible.
                    style={{ width: `${Math.max(2, (l.count / max) * 100)}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function Semaines({ semaines }: { semaines: GovernanceResponse["service"]["weekly"] }) {
  const max = Math.max(1, ...semaines.map((w) => w.critical + w.high + w.medium + w.low));
  return (
    <div className="mt-1 flex items-end gap-3 overflow-x-auto pb-1">
      {semaines.map((w) => {
        const total = w.critical + w.high + w.medium + w.low;
        return (
          <div key={w.week} className="flex w-16 shrink-0 flex-col items-center gap-1">
            <span className="font-mono-data text-11 text-ink-dim">{total}</span>
            <div className="flex h-28 w-8 flex-col-reverse overflow-hidden rounded bg-panel-sunken">
              <div className="bg-info" style={{ height: `${(w.medium / max) * 100}%` }} />
              <div className="bg-warn" style={{ height: `${(w.high / max) * 100}%` }} />
              <div className="bg-critical" style={{ height: `${(w.critical / max) * 100}%` }} />
            </div>
            <span className="font-mono-label text-10 text-ink-faint">
              {new Date(`${w.week}T00:00:00Z`).toLocaleDateString("fr-FR", {
                day: "2-digit",
                month: "2-digit",
                timeZone: "UTC",
              })}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Mois({ mois }: { mois: GovernanceResponse["sector_threat"]["monthly"] }) {
  const max = Math.max(1, ...mois.map((x) => x.critical_sector + x.other));
  return (
    <div className="mt-1 flex items-end gap-2 overflow-x-auto pb-1">
      {mois.map((x) => (
        <div key={x.month} className="flex w-11 shrink-0 flex-col items-center gap-1">
          <span className="font-mono-data text-11 text-ink-dim">
            {x.critical_sector + x.other}
          </span>
          <div className="flex h-28 w-6 flex-col-reverse overflow-hidden rounded bg-panel-sunken">
            <div className="bg-signal/70" style={{ height: `${(x.other / max) * 100}%` }} />
            <div className="bg-warn" style={{ height: `${(x.critical_sector / max) * 100}%` }} />
          </div>
          <span className="font-mono-label text-10 text-ink-faint">
            {new Date(`${x.month}-01T00:00:00Z`).toLocaleDateString("fr-FR", {
              month: "short",
              year: "2-digit",
              timeZone: "UTC",
            })}
          </span>
        </div>
      ))}
    </div>
  );
}
