import { dateHeure } from "../../../lib/format";
import { Fait } from "./Fait";
import type { ContexteDossier } from "./contexte";

/** Renseignements tiers sur la victime : compteurs seulement, aucune donnée personnelle. */
export function RenseignementsVictime({ c }: { c: ContexteDossier }) {
  const { alerte, expositionMesuree } = c;
  return (
    <>
      {alerte.intel_refreshed_at ? (
        <section className="pulse-panel p-4">
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">
            Renseignements sur la victime
          </h2>
          <p className="mt-1 font-mono-label text-10.5 text-ink-dim">
            source : ransomware.live
          </p>
          <div className="mt-2.5 flex flex-col gap-2">
            {alerte.victim_attack_date ? (
              <Fait
                label="Date de l'attaque"
                valeur={dateHeure(alerte.victim_attack_date)}
                note="documentée par un observateur tiers"
              />
            ) : (
              <Fait
                label="Date de l'attaque"
                valeur="non datée de façon fiable"
                note="date non fiable, écartée"
              />
            )}
            {/* Valeur du TIERS (`computed_sector`) : la valeur retenue, qui
                peut venir de l'organisation ou d'un analyste, est affichée
                dans « Gravité, pays, secteur ». */}
            {(alerte.computed_sector ?? alerte.victim_sector) ? (
              <Fait
                label="Secteur"
                valeur={(alerte.computed_sector ?? alerte.victim_sector) as string}
                note="déclaré par l'observateur tiers"
              />
            ) : null}
            {expositionMesuree ? (
              <>
                <Fait
                  label="Identifiants d'employés exposés"
                  valeur={alerte.compromised_employees != null ? `${alerte.compromised_employees}` : "non fourni"}
                  note="personnel de l'organisation — nombre seul"
                  ton={(alerte.compromised_employees ?? 0) > 0 ? "warn" : "neutre"}
                />
                <Fait
                  label="Identifiants de clients exposés"
                  valeur={alerte.compromised_users != null ? `${alerte.compromised_users}` : "non fourni"}
                  note="nombre seul"
                />
                {(alerte.stealer_families ?? []).length > 0 ? (
                  <Fait
                    label="Familles de voleurs"
                    valeur={(alerte.stealer_families ?? []).join(", ")}
                    note="méthode déclarée, non vérifiée"
                  />
                ) : null}
              </>
            ) : (
              <p className="font-mono-label text-10.5 text-ink-dim">
                exposition d&apos;identifiants : non fournie par la source
              </p>
            )}
          </div>
          {(alerte.compromised_employees ?? 0) > 0 ? (
            <p className="mt-2.5 rounded-xl border border-warn/30 bg-panel-sunken p-2.5 text-body-sm text-ink">
              Identifiants d&apos;employés exposés : un chemin d&apos;intrusion existe.
            </p>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
