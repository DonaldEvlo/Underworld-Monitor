import { useSyncExternalStore } from "react";
import { sourcesApi, type SourceTestJob } from "../api/sources";

/**
 * État partagé du test de disponibilité des sources.
 *
 * ⚠️ HORS DES PAGES, À DESSEIN. Le test dure plusieurs minutes ; tant que son
 * résultat vivait dans l'état d'une page, changer de page ou un onglet
 * rechargé par le navigateur perdait tout (signalé à l'usage le 2026-09-11).
 * Le test tourne désormais côté serveur ; ce module ne fait que le suivre, et
 * retrouve le dernier test (`/test-jobs/latest`) à la première page qui
 * l'affiche — y compris après un rechargement complet.
 *
 * Collecte et Sources lisent le MÊME état : un test lancé sur l'une se suit
 * sur l'autre.
 */

interface EtatTest {
  job: SourceTestJob | null;
  demarrage: boolean;
  erreur: string | null;
}

const INTERVALLE_MS = 1500;
// Au-delà, le suivi s'arrête et le dit : un test expiré (24 h) ne doit pas
// être interrogé indéfiniment.
const ECHECS_MAX = 5;

let etat: EtatTest = { job: null, demarrage: false, erreur: null };
const abonnes = new Set<() => void>();
let minuteur: ReturnType<typeof setTimeout> | null = null;
let echecs = 0;
let initialise = false;

function publier(partiel: Partial<EtatTest>) {
  etat = { ...etat, ...partiel };
  for (const f of abonnes) f();
}

function arreterSuivi() {
  if (minuteur) clearTimeout(minuteur);
  minuteur = null;
}

function planifierSuivi(jobId: string) {
  arreterSuivi();
  // Personne ne regarde : inutile d'interroger le serveur. Le suivi reprend
  // au retour d'une page abonnée (voir `abonner`).
  if (abonnes.size === 0) return;
  minuteur = setTimeout(() => void suivre(jobId), INTERVALLE_MS);
}

async function suivre(jobId: string) {
  minuteur = null;
  try {
    const job = await sourcesApi.getTestJob(jobId);
    echecs = 0;
    publier({ job, erreur: null });
    if (job.status === "running") planifierSuivi(jobId);
  } catch (err) {
    echecs += 1;
    if (echecs >= ECHECS_MAX) {
      publier({
        erreur: `Suivi interrompu : ${err instanceof Error ? err.message : "serveur injoignable"}`,
      });
      return;
    }
    // Coupure passagère : le test continue côté serveur, on retente.
    planifierSuivi(jobId);
  }
}

function abonner(rappel: () => void) {
  abonnes.add(rappel);
  if (!initialise) {
    initialise = true;
    sourcesApi
      .getLatestTestJob()
      .then((job) => {
        // Un test lancé entre-temps depuis cette session prime.
        if (etat.job === null) publier({ job });
        if (job.status === "running") planifierSuivi(job.job_id);
      })
      .catch(() => {
        // 404 = aucun test depuis 24 h : rien à afficher, ce n'est pas une erreur.
      });
  } else if (etat.job?.status === "running" && minuteur === null) {
    planifierSuivi(etat.job.job_id);
  }
  return () => {
    abonnes.delete(rappel);
    if (abonnes.size === 0) arreterSuivi();
  };
}

/** Lance un test (toutes les sources, les actives, ou une seule). Si un test
 * tourne déjà, le serveur rend CELUI-LÀ : l'écran le suit plutôt que d'en
 * lancer un second. */
export async function lancerTestSources(options: { onlyActive?: boolean; sourceId?: string }) {
  publier({ demarrage: true, erreur: null });
  try {
    const job = await sourcesApi.startTestJob({
      only_active: options.onlyActive ?? false,
      source_id: options.sourceId,
    });
    echecs = 0;
    publier({ job, demarrage: false });
    if (job.status === "running") planifierSuivi(job.job_id);
  } catch (err) {
    publier({
      demarrage: false,
      erreur: err instanceof Error ? err.message : "Lancement du test impossible",
    });
  }
}

export function useTestSources(): EtatTest {
  return useSyncExternalStore(abonner, () => etat);
}
