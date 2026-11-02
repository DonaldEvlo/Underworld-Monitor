import { useState } from "react";
import { alertsApi, type ValueOrigin } from "../../../api/alerts";
import { entitiesApi } from "../../../api/entities";
import { useRequete } from "../../../hooks/useRequete";
import { nomPays } from "../../../lib/alertes";
import { dateHeure } from "../../../lib/format";
import { severityLabels, severityTexte } from "../../../lib/taxonomy";
import type { AlertSeverity } from "../../../types/domain";
import type { ContexteDossier } from "./contexte";

const GRAVITES: AlertSeverity[] = ["critical", "high", "medium", "low"];

const CHAMP =
  "rounded-lg border border-line bg-panel-sunken px-2.5 py-1.5 text-body-sm text-ink outline-none transition-colors focus:border-signal/60 disabled:opacity-50";

function origine(o: ValueOrigin | null | undefined, par?: string | null): string {
  if (o === "analyst") return `corrigé par ${par ?? "un analyste"}`;
  if (o === "organization") return "déclaré par l'organisation";
  if (o === "computed") return "calcul de la plateforme";
  return "non renseigné";
}

/** Gravité, pays et secteur : la valeur retenue, d'où elle vient, et la
 * correction de l'analyste (migration 0033).
 *
 * ⚠️ La valeur CALCULÉE reste affichée à côté d'une correction : l'écart
 * entre la plateforme et l'humain est précisément ce qui se mesure ensuite.
 * Le motif est obligatoire ; les passes horaires ne réécrivent jamais une
 * valeur corrigée.
 */
export function CorrectionAnalyste({ c }: { c: ContexteDossier }) {
  const { alerte, agir, enCours } = c;
  const secteurs = useRequete(() => entitiesApi.sectors(), []).donnees ?? [];
  const [ouvert, setOuvert] = useState(false);
  const [gravite, setGravite] = useState<AlertSeverity | "">(alerte.severity_override ?? "");
  const [pays, setPays] = useState(alerte.country_override ?? "");
  const [secteur, setSecteur] = useState(alerte.sector_override ?? "");
  const [motif, setMotif] = useState(alerte.override_reason ?? "");

  const libelleSecteur = (v: string | null | undefined) =>
    v ? (secteurs.find((s) => s.value === v)?.label ?? v) : null;
  const corrigee = Boolean(alerte.severity_override || alerte.country_override || alerte.sector_override);
  const rienDemande = !gravite && !pays.trim() && !secteur;
  const paysInvalide = pays.length > 0 && pays.length !== 2;

  function ouvrir() {
    setGravite(alerte.severity_override ?? "");
    setPays(alerte.country_override ?? "");
    setSecteur(alerte.sector_override ?? "");
    setMotif(alerte.override_reason ?? "");
    setOuvert(true);
  }

  const lignes: { label: string; valeur: string | null; calcul: string | null; origine: string; ton?: string }[] = [
    {
      label: "Gravité",
      valeur: severityLabels[alerte.severity],
      calcul:
        alerte.severity_origin === "analyst" && alerte.computed_severity
          ? severityLabels[alerte.computed_severity]
          : null,
      origine: origine(alerte.severity_origin, alerte.override_by),
      ton: severityTexte[alerte.severity],
    },
    {
      label: "Pays",
      valeur: nomPays(alerte.victim_country),
      calcul:
        alerte.country_origin !== "computed" && alerte.computed_country
          ? nomPays(alerte.computed_country)
          : null,
      origine: alerte.victim_country ? origine(alerte.country_origin, alerte.override_by) : "non renseigné",
    },
    {
      label: "Secteur",
      valeur: libelleSecteur(alerte.victim_sector),
      calcul:
        alerte.sector_origin !== "computed" && alerte.computed_sector
          ? libelleSecteur(alerte.computed_sector)
          : null,
      origine: alerte.victim_sector ? origine(alerte.sector_origin, alerte.override_by) : "non renseigné",
    },
  ];

  return (
    <section className="pulse-panel p-4">
      <h2 className="font-display text-15 font-bold tracking-tight text-ink">Gravité, pays, secteur</h2>
      <div className="mt-2.5 flex flex-col gap-2">
        {lignes.map((l) => (
          <div key={l.label} className="rounded-xl border border-line bg-panel-sunken p-3">
            <p className="font-mono-label text-10 uppercase tracking-widest text-ink-faint">{l.label}</p>
            <p className={`mt-1 font-mono-data text-14 ${l.ton ?? "text-ink"}`}>{l.valeur ?? "—"}</p>
            <p className="mt-1 text-body-sm text-ink-dim">
              {l.origine}
              {l.calcul && ` · source tierce / calcul : ${l.calcul}`}
            </p>
          </div>
        ))}
      </div>

      {corrigee && !ouvert && (
        <p className="mt-2.5 rounded-xl border border-line bg-panel-sunken p-2.5 text-body-sm text-ink">
          <span className="text-ink-dim">Motif :</span> {alerte.override_reason}
          {alerte.override_at && (
            <span className="block font-mono-label text-10 text-ink-faint">
              {alerte.override_by ?? "analyste"} · {dateHeure(alerte.override_at)}
            </span>
          )}
        </p>
      )}

      {ouvert ? (
        <div className="mt-3 flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-12 text-ink-dim">
            Gravité
            <select value={gravite} onChange={(e) => setGravite(e.target.value as AlertSeverity | "")} className={CHAMP}>
              <option value="">calcul de la plateforme</option>
              {GRAVITES.map((g) => (
                <option key={g} value={g}>
                  {severityLabels[g]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-12 text-ink-dim">
            Pays (code ISO à deux lettres)
            <span className="flex items-center gap-2">
              <input
                value={pays}
                onChange={(e) => setPays(e.target.value.toUpperCase().slice(0, 2))}
                placeholder="ISO"
                className={`${CHAMP} w-16 font-mono-data uppercase placeholder:normal-case placeholder:text-ink-faint`}
              />
              <span className="text-11 text-ink-faint">
                {pays.length === 2 ? nomPays(pays) : "vide = valeur déclarée ou calculée"}
              </span>
            </span>
          </label>
          <label className="flex flex-col gap-1 text-12 text-ink-dim">
            Secteur
            <select value={secteur} onChange={(e) => setSecteur(e.target.value)} className={CHAMP}>
              <option value="">valeur déclarée ou calculée</option>
              {secteurs.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                  {s.critical ? " (NIS2)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label htmlFor="motif-correction" className="text-12 text-ink-dim">
            Motif (obligatoire)
          </label>
          <textarea
            id="motif-correction"
            value={motif}
            onChange={(e) => setMotif(e.target.value)}
            rows={3}
            maxLength={1000}
            placeholder="Ex. : l'annonce du groupe situe la victime en Égypte (siège au Caire)."
            className="w-full resize-y rounded-xl border border-line bg-panel-sunken p-2.5 text-body-sm text-ink outline-none focus:border-signal/60"
          />
          <div className="flex flex-wrap gap-2">
            <button
              disabled={enCours !== null || rienDemande || paysInvalide || motif.trim().length < 5}
              onClick={() =>
                void agir("correction", async () => {
                  const a = await alertsApi.correct(alerte.id, {
                    severity: gravite || null,
                    country: pays.trim() || null,
                    sector: secteur || null,
                    reason: motif.trim(),
                  });
                  setOuvert(false);
                  return a;
                })
              }
              className="rounded-lg bg-signal px-3 py-1.5 text-body-sm font-semibold text-on-signal disabled:opacity-40"
            >
              {enCours === "correction" ? "Enregistrement…" : "Enregistrer la correction"}
            </button>
            <button
              onClick={() => setOuvert(false)}
              className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim hover:text-ink"
            >
              Annuler
            </button>
          </div>
          <p className="font-mono-label text-10 text-ink-faint">
            le résumé IA est effacé : il décrivait les anciennes valeurs
          </p>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={ouvrir}
            disabled={enCours !== null}
            className="rounded-lg border border-line bg-panel-raised px-3 py-1.5 text-body-sm text-ink transition-colors hover:border-signal/40 disabled:opacity-40"
          >
            {corrigee ? "Modifier la correction" : "Corriger"}
          </button>
          {corrigee && (
            <button
              onClick={() => void agir("annulation", () => alertsApi.cancelCorrection(alerte.id))}
              disabled={enCours !== null}
              className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim hover:text-ink disabled:opacity-40"
            >
              {enCours === "annulation" ? "Annulation…" : "Annuler la correction"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
