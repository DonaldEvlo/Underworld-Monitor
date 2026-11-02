import { ageRelatif } from "../../../lib/alertes";
import {
  admiraltyInfoLabels,
  admiraltySourceLabels,
  credibilityLabel,
  credibilityTone,
  type CredibilityLevel,
} from "../../../lib/taxonomy";
import { dateHeure } from "../../../lib/format";
import { Fait } from "./Fait";
import type { ContexteDossier } from "./contexte";

/** Faits établis, produits par le code (jamais par le modèle). */
export function FaitsEtablis({ c }: { c: ContexteDossier }) {
  const { alerte, confirmee, exclusive, sansObjet, autresGroupes, observateurs, documents, documentPrincipal, avance, preuves } = c;
  return (
    <>
      {/* ---- faits établis ---- */}
      <section className="pulse-panel p-4">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">
          Faits établis
        </h2>
        <p className="mt-0.5 font-mono-label text-10.5 text-ink-faint">
          produits par le code, jamais par le modèle
        </p>
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
          {/* Crédibilité : axe DISTINCT de la gravité (« la fuite est-elle
              réelle ? »), toujours affichée avec sa preuve. */}
          <Fait
            label="Crédibilité"
            valeur={credibilityLabel(alerte.credibility_level) ?? "pas encore évaluée"}
            note={
              alerte.credibility_evidence ??
              "Évaluée à la prochaine génération des alertes."
            }
            ton={
              alerte.credibility_level && alerte.credibility_level in credibilityTone
                ? credibilityTone[alerte.credibility_level as CredibilityLevel]
                : "neutre"
            }
          />
          {/* Notation Admiralty : vocabulaire standard du renseignement.
              Lettre = historique MESURÉ de la source, chiffre = axe
              crédibilité. Jamais « A » : une revendication d'attaquant. */}
          {alerte.admiralty_code && (
            <Fait
              label="Notation Admiralty"
              valeur={`${alerte.admiralty_code} — source ${
                admiraltySourceLabels[alerte.admiralty_source ?? ""] ?? "?"
              }, information ${
                admiraltyInfoLabels[alerte.admiralty_information ?? ""] ?? "?"
              }`}
              note={`${alerte.admiralty_source_name ?? "Source"} : ${
                alerte.admiralty_source_reason ?? "—"
              }. Information : ${alerte.admiralty_information_reason ?? "—"}.`}
            />
          )}
          <Fait
            label="Revendication"
            valeur={alerte.corroborated_group ?? documentPrincipal?.source_name ?? "—"}
            note="Groupe attaquant — auteur présumé, pas un observateur."
            ton="critique"
          />
          <Fait
            label="Vérification externe"
            valeur={
              confirmee
                ? `confirmée · ${alerte.corroborated_group ?? "tiers"}${
                    autresGroupes.length ? ` +${autresGroupes.length}` : ""
                  }`
                : exclusive
                  ? "vue par nous seuls"
                  : sansObjet
                    ? "sans objet"
                    : "jamais confrontée"
            }
            note={
              confirmee
                ? // ⚠️ RansomLook lit LE MÊME site du gang : il confirme que
                  // l'annonce existe et que notre lecture est juste, pas que
                  // la fuite est réelle. Le dire, plutôt que « tiers de confiance ».
                  `${observateurs.length ? observateurs.join(" + ") : "Un observateur tiers"} a indexé la même annonce${avance ? ` — ${avance}` : ""}.${
                    autresGroupes.length ? ` Revendiquée aussi par : ${autresGroupes.join(", ")}.` : ""
                  }`
                : exclusive
                  ? "Non retrouvée chez les agrégateurs."
                  : sansObjet
                    ? "Mention de forum, pas une revendication."
                    : "Pas encore confrontée."
            }
            ton={confirmee ? "ok" : "neutre"}
          />
          <Fait
            label="Détections rattachées"
            valeur={String(alerte.detection_count)}
            note={`Réparties sur ${preuves?.document_count ?? documents.length} document(s) source.`}
          />
          <Fait
            label="Découverte"
            valeur={dateHeure(alerte.created_at)}
            note={`Ouverte ${ageRelatif(alerte.created_at)}${
              alerte.assignee ? ` · assignée à ${alerte.assignee}` : " · non assignée"
            }.`}
            ton={alerte.assignee ? "neutre" : "warn"}
          />
        </div>
      </section>
    </>
  );
}
