import { Link } from "react-router-dom";
import { alertsApi, type AlertApi } from "../../api/alerts";
import { entitiesApi, type EntityApi } from "../../api/entities";
import {
  ageRelatif,
  domaineAlerte,
  libelleCorroboration,
  parGraviteEtFraicheur,
  referenceCourte,
  sujetAlerte,
} from "../../lib/alertes";
import { severityFond, severityLabels, severityTexte } from "../../lib/taxonomy";
import { Icon } from "../ui/Icon";
import { dateHeure } from "../../lib/format";
import { useRequete } from "../../hooks/useRequete";
import { hrefSur } from "../../lib/liens";

/** Combien d'alertes la file affiche avant de renvoyer vers la page complete. */
const TAILLE_FILE = 6;

/** Couleur du liseré de gravité.
 *
 * ⚠️ Classes ECRITES EN TOUTES LETTRES : Tailwind analyse le source a la
 * compilation, une classe construite par concatenation (`border-${x}`) n'est
 * jamais generee et la couleur disparait silencieusement en production.
 */


function Puce({ texte, ton }: { texte: string; ton: "critique" | "ok" | "neutre" }) {
  const styles = {
    critique: "border-critical/40 bg-critical/12 text-critical",
    ok: "border-ok/35 bg-ok/10 text-ok",
    neutre: "border-line bg-panel-raised text-ink-dim",
  }[ton];
  return (
    <span className={`rounded-md border px-2 py-0.5 font-mono-label text-11 ${styles}`}>
      {texte}
    </span>
  );
}

export function FileDeVeille() {
  // Bornée : le poste de veille montre la tête de file, pas le corpus
  // d'alertes (la page Alertes pagine). Un échec laisse le panneau muet
  // plutôt qu'un écran cassé : le bandeau d'état reste lisible.
  const requete = useRequete(async () => {
    const [reponse, entites] = await Promise.all([
      alertsApi.list({ status: "open", limit: 60 }),
      entitiesApi.list(),
    ]);
    return {
      alertes: reponse.items,
      total: reponse.total,
      entitesParId: Object.fromEntries(entites.map((e) => [e.id, e])),
    };
  }, []);
  const alertes: AlertApi[] = requete.donnees?.alertes ?? [];
  const entitesParId: Record<string, EntityApi> = requete.donnees?.entitesParId ?? {};
  const total = requete.donnees?.total ?? 0;
  const chargement = requete.chargement;

  const triees = [...alertes].sort(parGraviteEtFraicheur);
  const tete = triees[0];
  const reste = triees.slice(1, 1 + TAILLE_FILE);

  if (chargement) {
    return (
      <div className="pulse-panel p-6">
        <p className="text-body-sm text-ink-faint">Chargement de la file…</p>
      </div>
    );
  }

  if (!tete) {
    return (
      <div className="pulse-panel flex flex-col items-center gap-2 p-10 text-center">
        <p className="font-display text-headline-md text-ink">Aucune alerte ouverte</p>
        <p className="max-w-md text-body-sm text-ink-dim">
          Rien n&apos;attend de décision.
        </p>
        <Link
          to="/alerts"
          className="mt-2 rounded-md border border-line bg-panel-raised px-3.5 py-2 text-body-sm text-ink transition-colors hover:border-signal/40"
        >
          Voir l&apos;historique
        </Link>
      </div>
    );
  }

  const corrTete = libelleCorroboration(tete);
  const domaineTete = domaineAlerte(tete, entitesParId);
  const critique = tete.severity === "critical";

  return (
    <div className="flex flex-col gap-3.5">
      {/* ---- À traiter en premier ------------------------------------- */}
      <section
        className={`overflow-hidden rounded-[18px] bg-panel ${
          critique ? "border border-critical/35" : "border border-signal/[0.14]"
        }`}
      >
        <div
          className={`flex items-center gap-2.5 border-b border-line px-4 py-2.5 ${
            critique ? "bg-critical/[0.07]" : "bg-panel-raised/40"
          }`}
        >
          <span
            className={`h-2 w-2 rounded-full ${severityFond[tete.severity]} ${
              critique ? "animate-pulse-critical" : ""
            }`}
          />
          <span
            className={`font-mono-label text-10 uppercase tracking-widest ${severityTexte[tete.severity]}`}
          >
            À traiter en premier · {severityLabels[tete.severity]}
          </span>
          <span
            className="ml-auto font-mono-label text-11 text-ink-dim"
            title={dateHeure(tete.created_at)}
          >
            ouverte {ageRelatif(tete.created_at)}
          </span>
        </div>

        <div className="flex flex-col gap-5 p-4 md:flex-row">
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-19 font-bold tracking-tight text-ink">
              {sujetAlerte(tete, entitesParId)}
            </h2>
            <p className="mt-0.5 font-mono-data text-mono-data text-ink-dim">
              {domaineTete ? `${domaineTete} · ` : ""}alerte {referenceCourte(tete)}
            </p>

            <div className="mt-3 flex flex-wrap gap-2">
              <Puce
                texte={corrTete.texte}
                ton={corrTete.ton === "ok" ? "ok" : "neutre"}
              />
              <Puce texte={`${tete.detection_count} détections`} ton="neutre" />
              {tete.assignee ? (
                <Puce texte={`assignée · ${tete.assignee}`} ton="neutre" />
              ) : (
                <Puce texte="non assignée" ton="critique" />
              )}
            </div>

            <p className="mt-3 max-w-[60ch] text-body-md text-ink">
              {tete.summary ?? (
                <span className="text-ink-dim">
                  Pas encore résumée — ouvrez le dossier pour voir les faits établis et la chaîne
                  documentaire.
                </span>
              )}
            </p>
          </div>

          <div className="flex w-full shrink-0 flex-col gap-2 md:w-52">
            <Link
              to={`/alerts/${tete.id}`}
              className="rounded-lg bg-signal px-3 py-2.5 text-center text-body-sm font-bold text-on-signal transition-opacity hover:opacity-90"
            >
              Ouvrir le dossier
            </Link>
            {tete.corroboration_evidence_url && (
              <a
                href={hrefSur(tete.corroboration_evidence_url)}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-center gap-1.5 rounded-lg border border-line bg-panel-raised px-3 py-2.5 text-center text-body-sm text-ink transition-colors hover:border-signal/40"
              >
                Voir la preuve
                <Icon name="open_in_new" className="text-15" />
              </a>
            )}
            <Link
              to="/alerts"
              className="rounded-lg border border-line px-3 py-2.5 text-center text-body-sm text-ink-dim transition-colors hover:text-ink"
            >
              Toutes les alertes
            </Link>
          </div>
        </div>
      </section>

      {/* ---- Votre file ------------------------------------------------ */}
      {reste.length > 0 && (
        <section className="pulse-panel p-4">
          <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">
              Votre file
            </h2>
            <p className="font-mono-label text-11 text-ink-faint">
              {total} ouvertes · triées par gravité puis fraîcheur
            </p>
          </div>

          <div className="flex flex-col gap-1.5">
            {reste.map((alerte) => {
              const corr = libelleCorroboration(alerte);
              const domaine = domaineAlerte(alerte, entitesParId);
              return (
                <Link
                  key={alerte.id}
                  to={`/alerts/${alerte.id}`}
                  className="grid grid-cols-[3px_1fr_auto] items-center gap-x-3.5 overflow-hidden rounded-xl border border-line bg-panel-sunken pr-3 transition-colors hover:border-signal/30 md:grid-cols-[3px_1fr_7rem_9rem_5.5rem_5.5rem]"
                >
                  {/* ⚠️ Le liseré porte la gravité : la file se lit en balayage,
                      sans chercher la pastille ligne par ligne. */}
                  <span className={`h-[46px] ${severityFond[alerte.severity]}`} />
                  <div className="min-w-0 py-2">
                    <p className="truncate text-body-sm font-semibold text-ink">
                      {sujetAlerte(alerte, entitesParId)}
                    </p>
                    <p className="truncate font-mono-data text-11 text-ink-dim">
                      {domaine ?? `alerte ${referenceCourte(alerte)}`}
                    </p>
                  </div>
                  <span
                    className={`hidden font-mono-label text-11 md:block ${severityTexte[alerte.severity]}`}
                  >
                    {severityLabels[alerte.severity]}
                  </span>
                  <span
                    className={`hidden truncate font-mono-label text-11 md:block ${
                      corr.ton === "ok" ? "text-ok" : "text-ink-dim"
                    }`}
                  >
                    {corr.texte}
                  </span>
                  <span className="hidden font-mono-data text-11 tabular-nums text-ink-dim md:block">
                    {alerte.detection_count} détect.
                  </span>
                  <span
                    className="hidden whitespace-nowrap text-right font-mono-data text-11 text-ink-faint md:block"
                    title={dateHeure(alerte.created_at)}
                  >
                    {ageRelatif(alerte.created_at)}
                  </span>
                </Link>
              );
            })}
          </div>

          {total > reste.length + 1 && (
            <Link
              to="/alerts"
              className="mt-3 flex items-center gap-1.5 border-t border-line-soft pt-3 font-mono-label text-11 text-signal"
            >
              Voir les {total} alertes ouvertes
              <Icon name="chevron_right" className="text-14" />
            </Link>
          )}
        </section>
      )}
    </div>
  );
}
