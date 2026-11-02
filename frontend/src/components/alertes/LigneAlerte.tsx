import { Link } from "react-router-dom";
import type { AlertApi } from "../../api/alerts";
import type { EntityApi } from "../../api/entities";
import {
  ageRelatif,
  domaineAlerte,
  faitsAlerte,
  libelleCorroboration,
  sujetAlerte,
} from "../../lib/alertes";
import { dateHeure } from "../../lib/format";
import {
  credibilityLabel,
  severityFond,
  severityLabels,
  severityTexte,
  statusLabels,
} from "../../lib/taxonomy";

// Niveaux de crédibilité qui méritent un badge dans la liste. `published` et
// `not_evaluated` en sont absents volontairement (voir le rendu des lignes).
// ⚠️ Rouge et orange sont les couleurs de la GRAVITÉ : « revendiquée
// seulement » en orange se lisait comme une gravité élevée. Badges de
// crédibilité en contour neutre ; seul « confirmée » garde le vert, qui n'est
// pas une couleur de gravité.
const BADGE_CREDIBILITE: Record<string, string | undefined> = {
  confirmed: "bg-ok/[0.12] text-ok",
  doubtful: "border border-ink-dim/60 text-ink",
  claimed: "border border-line text-ink-dim",
};
// Une seule définition de la grille, partagée par l'en-tête et les lignes :
// deux copies finiraient par se décaler d'une colonne.
const GRILLE =
  "grid-cols-[4px_minmax(0,1fr)_auto] md:grid-cols-[4px_minmax(0,1fr)_6.5rem_9.5rem_6rem_5.5rem_6.5rem]";

/** En-têtes de la liste. Sans eux, « sans objet » ou « 1 » ne se lisaient pas. */
export function EnteteListeAlertes() {
  return (
    <div
      className={`hidden gap-x-4 pr-4 font-mono-label text-10 uppercase tracking-wide text-ink-dim md:grid ${GRILLE}`}
    >
      <span />
      <span>Victime · faits</span>
      <span>Gravité</span>
      <span>Confirmation tierce</span>
      <span>Détections</span>
      <span>Détectée</span>
      <span className="justify-self-end">Statut</span>
    </div>
  );
}

/** Une ligne de la file d'alertes : un lien vers le dossier. */
export function LigneAlerte({
  alerte: a,
  entitiesById,
}: {
  alerte: AlertApi;
  entitiesById: Record<string, EntityApi>;
}) {
  const corr = libelleCorroboration(a);
  const domaine = domaineAlerte(a, entitiesById);
  const faits = faitsAlerte(a);
  return (
    <Link
      to={`/alerts/${a.id}`}
      className={`grid items-center gap-x-4 overflow-hidden rounded-[14px] border border-line bg-panel pr-4 transition-colors hover:border-signal/30 hover:bg-[#111925] ${GRILLE}`}
    >
      <span className={`h-11 ${severityFond[a.severity]}`} />
      <div className="min-w-0 py-3">
        <p className="flex min-w-0 items-center gap-2">
          <span className="truncate font-semibold text-ink">
            {a.victim_label ?? sujetAlerte(a, entitiesById)}
          </span>
          {a.group_name && (
            <span className="shrink-0 rounded-md bg-panel-raised px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
              groupe · {a.group_name}
            </span>
          )}
          {a.scope === "region" && (
            <span className="shrink-0 rounded-md border border-line px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
              non déclarée · {a.region}
            </span>
          )}
          {/* Badge seul : la ligne entière est déjà un lien, un
              lien imbriqué serait invalide. L'article est
              cliquable dans le dossier. */}
          {/* Crédibilité : badge seulement pour ce qui se
              DISTINGUE. « Publiée par le groupe » concerne
              l'essentiel des alertes : le répéter sur chaque
              ligne serait du bruit (il reste dans le dossier). */}
          {a.credibility_level && BADGE_CREDIBILITE[a.credibility_level] && (
            <span
              className={`shrink-0 rounded-md px-1.5 py-0.5 font-mono-label text-10 ${
                BADGE_CREDIBILITE[a.credibility_level]
              }`}
              title={a.credibility_evidence ?? undefined}
            >
              {a.credibility_level === "confirmed"
                ? "confirmée · presse"
                : credibilityLabel(a.credibility_level)?.toLowerCase()}
            </span>
          )}
        </p>
        <p className="truncate text-body-sm text-ink-dim" title={a.summary ?? undefined}>
          {/* Sans renseignement tiers : le domaine et le constat,
              jamais le début du résumé (« Une alerte de… » répète
              la gravité). Le résumé reste en infobulle et au dossier. */}
          {faits.length > 0 ? (
            faits.join(" · ")
          ) : (
            <span className="font-mono-data text-11">
              {domaine ? `${domaine} · ` : ""}aucun renseignement tiers (secteur, pays, date)
            </span>
          )}
        </p>
      </div>
      <span
        className={`hidden font-mono-data text-11 md:block ${severityTexte[a.severity]}`}
        title={
          a.severity_origin === "analyst" && a.computed_severity
            ? `Corrigée par ${a.override_by ?? "un analyste"} (calcul : ${severityLabels[a.computed_severity].toLowerCase()})`
            : undefined
        }
      >
        {severityLabels[a.severity].toLowerCase()}
        {a.severity_origin === "analyst" && <span className="text-ink-faint"> · corrigée</span>}
      </span>
      <span
        className={`hidden truncate font-mono-data text-11 md:block ${
          corr.ton === "ok" ? "text-ok" : "text-ink-dim"
        }`}
        title={
          a.corroboration_status === "not_applicable"
            ? "Annonce reçue d'un agrégateur, ou simple mention de forum : rien à confronter"
            : undefined
        }
      >
        {corr.texte}
      </span>
      <span className="hidden font-mono-data text-11 text-ink-dim md:block">
        {a.detection_count}
      </span>
      <span
        className="hidden font-mono-data text-11 text-ink-faint md:block"
        title={dateHeure(a.created_at)}
      >
        {ageRelatif(a.created_at)}
      </span>
      <span className="justify-self-end rounded-md bg-panel-raised px-2 py-0.5 font-mono-label text-10 text-ink-dim">
        {a.resolution_reason === "false_positive" ? "faux positif" : statusLabels[a.status]}
      </span>
    </Link>
  );
}
