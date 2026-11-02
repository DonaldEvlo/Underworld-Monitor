import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { alertsApi } from "../../api/alerts";
import { entitiesApi } from "../../api/entities";
import { schedulesApi, type ScheduleApi } from "../../api/schedules";
import { useVeilleBadges } from "../../hooks/useVeilleBadges";
import { useEscapeKey } from "../../hooks/useEscapeKey";
import { ageRelatif, parGraviteEtFraicheur, sujetAlerte } from "../../lib/alertes";
import { severityFond, severityLabels, severityTexte } from "../../lib/taxonomy";
import { useRequete } from "../../hooks/useRequete";
import {
  LIBELLE_NIVEAU,
  etatGlobal,
  evaluerTache,
  type NiveauGlobal,
  type NiveauTache,
} from "../../lib/etatPlateforme";
import { Icon } from "../ui/Icon";
import { dateHeure } from "../../lib/format";

/** Cloche : un résumé bref des alertes, puis « Afficher tout ».
 *
 * ⚠️ Le clic menait droit à la liste : pour savoir s'il y avait du nouveau, il
 * fallait quitter la page en cours. Le panneau répond à « qu'est-ce qui
 * m'attend ? » sans navigation ; la liste reste à un clic.
 * Compteurs : cache partagé avec la barre latérale (aucun appel de plus). Les
 * alertes ne sont chargées qu'à l'OUVERTURE du panneau. */
export function ClocheAlertes() {
  const activite = useVeilleBadges();
  const [ouvert, setOuvert] = useState(false);
  const fermer = useCallback(() => setOuvert(false), []);
  useEscapeKey(ouvert, fermer);
  const nouvelles = activite?.nouvelles_alertes ?? 0;
  const graves = activite?.nouvelles_alertes_graves ?? 0;
  const libelle =
    nouvelles === 0
      ? "Alertes : aucune nouvelle depuis 24 h"
      : `Alertes : ${nouvelles} nouvelle(s) depuis 24 h${graves ? `, dont ${graves} grave(s)` : ""}`;

  // Tête de file : les plus graves d'abord, puis les plus récentes — le même
  // ordre que la page Alertes.
  const file = useRequete(
    async () => {
      const [reponse, entites] = await Promise.all([
        alertsApi.list({ status: "open", limit: 60 }),
        entitiesApi.list(),
      ]);
      return {
        tete: [...reponse.items].sort(parGraviteEtFraicheur).slice(0, APERCU_MAX),
        total: reponse.total,
        entitesParId: Object.fromEntries(entites.map((e) => [e.id, e])),
      };
    },
    [],
    { actif: ouvert },
  );

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOuvert((o) => !o)}
        aria-haspopup="dialog"
        aria-expanded={ouvert}
        title={libelle}
        aria-label={libelle}
        className="relative rounded-md p-1.5 text-ink-dim transition-all hover:bg-panel-raised hover:text-signal"
      >
        <Icon name={nouvelles ? "notifications_active" : "notifications"} />
        {nouvelles > 0 && (
          <span
            aria-hidden
            className={`absolute -right-0.5 -top-0.5 min-w-[16px] rounded-full px-1 text-center font-mono-label text-10 font-bold leading-4 ${
              graves ? "bg-critical text-white" : "bg-signal text-on-signal"
            }`}
          >
            {nouvelles > 99 ? "99+" : nouvelles}
          </span>
        )}
      </button>
      {ouvert && (
        <>
          <div className="fixed inset-0 z-40" onClick={fermer} />
          <div
            role="dialog"
            aria-label="Résumé des alertes"
            className="absolute right-0 top-full z-50 mt-3 w-[360px] max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-panel-sunken p-3 shadow-2xl"
          >
            <p className="font-mono-label text-mono-label uppercase tracking-widest text-ink-dim">
              Alertes
            </p>
            <p className="mt-1 text-body-sm font-semibold text-ink">
              {nouvelles === 0 ? (
                "Aucune nouvelle alerte depuis 24 h"
              ) : (
                <>
                  {nouvelles} nouvelle(s) depuis 24 h
                  {graves > 0 && <span className="text-critical"> · dont {graves} grave(s)</span>}
                </>
              )}
            </p>
            {activite && (
              <p className="mt-0.5 text-12 text-ink-dim">
                {activite.alertes_ouvertes} ouverte(s) · {activite.alertes_non_affectees} non
                affectée(s)
              </p>
            )}

            <div className="mt-3 border-t border-line-soft pt-2.5">
              <p className="mb-1.5 font-mono-label text-10 uppercase tracking-widest text-ink-faint">
                À traiter en premier
              </p>
              {file.chargement && <p className="text-body-sm text-ink-dim">Chargement…</p>}
              {file.erreur && <p className="text-body-sm text-critical">{file.erreur}</p>}
              {file.donnees && file.donnees.tete.length === 0 && (
                <p className="text-body-sm text-ink-dim">Aucune alerte ouverte.</p>
              )}
              {file.donnees && file.donnees.tete.length > 0 && (
                <ul className="flex flex-col gap-0.5">
                  {file.donnees.tete.map((a) => (
                    <li key={a.id}>
                      <Link
                        to={`/alerts/${a.id}`}
                        onClick={fermer}
                        className="flex items-center gap-2 rounded-md px-1.5 py-1.5 transition-colors hover:bg-panel-raised"
                      >
                        <span
                          className={`h-2 w-2 shrink-0 rounded-full ${severityFond[a.severity]}`}
                          title={severityLabels[a.severity]}
                        />
                        <span className="min-w-0 flex-1 truncate text-body-sm text-ink">
                          {a.victim_label ?? sujetAlerte(a, file.donnees?.entitesParId ?? {})}
                        </span>
                        <span className={`shrink-0 font-mono-label text-10 ${severityTexte[a.severity]}`}>
                          {severityLabels[a.severity].toLowerCase()}
                        </span>
                        <span className="shrink-0 whitespace-nowrap text-right font-mono-label text-10 text-ink-faint">
                          {ageRelatif(a.created_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <Link
              to="/alerts"
              onClick={fermer}
              className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-signal/30 bg-signal/10 px-3 py-2 text-body-sm font-semibold text-signal transition-colors hover:bg-signal/20"
            >
              Afficher tout
              {file.donnees ? ` (${file.donnees.total})` : ""}
              <Icon name="chevron_right" className="text-14" />
            </Link>
          </div>
        </>
      )}
    </div>
  );
}

// Lignes de tête de file affichées dans le panneau de la cloche.
const APERCU_MAX = 5;

// Cache de module : le bandeau est remonté à CHAQUE navigation (chaque page
// rend son propre AppLayout), même raison que `useVeilleBadges`.
const DUREE_CACHE_MS = 60_000;
let cache: { valeur: ScheduleApi[]; expire: number } | null = null;

async function chargerTaches(forcer: boolean): Promise<ScheduleApi[]> {
  if (!forcer && cache && cache.expire > Date.now()) return cache.valeur;
  const reponse = await schedulesApi.list();
  cache = { valeur: reponse.schedules, expire: Date.now() + DUREE_CACHE_MS };
  return reponse.schedules;
}

const COULEUR_GLOBALE: Record<NiveauGlobal, string> = {
  ok: "text-ink-dim",
  attention: "text-warn",
  panne: "text-critical",
};

const PASTILLE_GLOBALE: Record<NiveauGlobal, string> = {
  ok: "bg-signal",
  attention: "bg-warn",
  panne: "bg-critical",
};

const TITRE_GLOBAL: Record<NiveauGlobal, string> = {
  ok: "Plateforme opérationnelle",
  attention: "Plateforme opérationnelle, des sources en échec",
  panne: "Chaîne interrompue : une tâche échoue ou ne passe plus",
};

const COULEUR_TACHE: Record<NiveauTache, string> = {
  ok: "border-signal/40 text-signal",
  erreur: "border-critical/50 text-critical",
  retard: "border-critical/50 text-critical",
  suspendue: "border-line text-ink-faint",
  jamais: "border-warn/40 text-warn",
};

/** Bouclier : « la chaîne tourne-t-elle vraiment ? » (voir lib/etatPlateforme).
 *
 * ⚠️ Remplace un bouton « Statut de sécurité » qui ne faisait RIEN. */
export function EtatPlateforme() {
  const activite = useVeilleBadges();
  // Horodaté au CHARGEMENT : le retard se juge à l'instant de la mesure, et
  // le rendu reste pur (pas de `Date.now()` pendant le rendu).
  const [mesure, setMesure] = useState<{ taches: ScheduleApi[]; a: number } | null>(() =>
    cache ? { taches: cache.valeur, a: cache.expire - DUREE_CACHE_MS } : null,
  );
  const [erreur, setErreur] = useState<string | null>(null);
  const [ouvert, setOuvert] = useState(false);
  const fermer = useCallback(() => setOuvert(false), []);
  useEscapeKey(ouvert, fermer);

  const recharger = useCallback((forcer: boolean) => {
    chargerTaches(forcer).then(
      (valeur) => {
        setMesure({ taches: valeur, a: Date.now() });
        setErreur(null);
      },
      (e: unknown) => {
        // Affiché, jamais avalé : un état de santé illisible est lui-même
        // une information.
        setErreur(e instanceof Error ? e.message : "État indisponible");
      },
    );
  }, []);

  useEffect(() => {
    recharger(false);
  }, [recharger]);

  const taches = mesure?.taches ?? null;
  const etats = (taches ?? []).map((t) => evaluerTache(t, mesure?.a ?? 0));
  const sourcesEnEchec = activite?.sources_en_echec ?? 0;
  const global: NiveauGlobal = erreur ? "attention" : etatGlobal(etats, sourcesEnEchec);
  const titre = erreur ? "État de la plateforme indisponible" : TITRE_GLOBAL[global];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          setOuvert((o) => !o);
          if (!ouvert) recharger(true);
        }}
        aria-haspopup="dialog"
        aria-expanded={ouvert}
        title={titre}
        aria-label={`État de la plateforme : ${titre}`}
        className={`relative rounded-md p-1.5 transition-all hover:bg-panel-raised hover:text-signal ${COULEUR_GLOBALE[global]}`}
      >
        <Icon name="shield" />
        {taches && global !== "ok" && (
          <span
            aria-hidden
            className={`absolute right-0.5 top-0.5 h-2 w-2 rounded-full ${PASTILLE_GLOBALE[global]}`}
          />
        )}
      </button>
      {ouvert && (
        <>
          <div className="fixed inset-0 z-40" onClick={fermer} />
          <div
            role="dialog"
            aria-label="État de la plateforme"
            className="absolute right-0 top-full z-50 mt-3 w-[340px] max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-panel-sunken p-3 shadow-2xl"
          >
            <p className="font-mono-label text-mono-label uppercase tracking-widest text-ink-dim">
              État de la plateforme
            </p>
            <p className={`mt-1 text-body-sm font-semibold ${COULEUR_GLOBALE[global] === "text-ink-dim" ? "text-signal" : COULEUR_GLOBALE[global]}`}>
              {titre}
            </p>
            {erreur && <p className="mt-2 text-body-sm text-critical">{erreur}</p>}
            {!taches && !erreur && <p className="mt-2 text-body-sm text-ink-dim">Chargement…</p>}
            {taches && (
              <ul className="mt-3 space-y-2">
                {etats.map(({ tache, niveau }) => (
                  <li key={tache.id} className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-body-sm text-ink" title={tache.label}>
                        {tache.label}
                      </p>
                      <p
                        className="text-11 text-ink-faint"
                        title={
                          tache.last_run_at
                            ? dateHeure(tache.last_run_at)
                            : undefined
                        }
                      >
                        {tache.last_run_at ? `dernier passage ${ageRelatif(tache.last_run_at)}` : "jamais exécutée"}
                        {niveau === "erreur" && tache.last_detail ? ` — ${tache.last_detail.slice(0, 80)}` : ""}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 rounded border px-1.5 py-0.5 font-mono-label text-10 uppercase ${COULEUR_TACHE[niveau]}`}
                    >
                      {LIBELLE_NIVEAU[niveau]}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {sourcesEnEchec > 0 && (
              <Link
                to="/sources"
                onClick={fermer}
                className="mt-3 flex items-center gap-2 rounded border border-warn/40 bg-warn-dim/30 px-2 py-1.5 text-body-sm text-warn hover:bg-warn-dim/50"
              >
                <Icon name="warning" className="text-16" />
                {sourcesEnEchec} source(s) en échec au dernier passage
              </Link>
            )}
            <Link
              to="/planification"
              onClick={fermer}
              className="mt-3 block text-right text-12 text-ink-dim underline-offset-2 hover:text-signal hover:underline"
            >
              Voir la planification
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
