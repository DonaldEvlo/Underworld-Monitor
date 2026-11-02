import type { ScheduleApi } from "../api/schedules";

/** État de la plateforme : la chaîne tourne-t-elle VRAIMENT ?
 *
 * ⚠️ Pourquoi ce panneau existe : l'alerting est resté EN PANNE six jours
 * (5 au 11 septembre 2026) avec pour seul signal une colonne `last_status`
 * que personne ne consultait. Et un poste éteint fait manquer des créneaux de
 * collecte que Celery Beat ne rattrape jamais. Une tâche qui échoue ou qui ne
 * passe plus doit se VOIR depuis n'importe quelle page.
 */

export type NiveauTache = "ok" | "erreur" | "retard" | "suspendue" | "jamais";
export type NiveauGlobal = "ok" | "attention" | "panne";

export interface EtatTache {
  tache: ScheduleApi;
  niveau: NiveauTache;
  /** Intervalle attendu entre deux passages, en heures (déduit de l'horaire). */
  intervalleH: number;
}

/** Marge ajoutée à l'intervalle avant de déclarer un retard : une tâche longue
 * (Dread ~25 min, liens jusqu'à ~2 h) enregistre son passage à la FIN. */
const MARGE_H = 2.5;

/** Plus grand écart entre deux passages, déduit du champ « heure » du cron.
 *
 * ⚠️ Un seuil unique serait faux : l'alerting passe toutes les heures, Dread
 * une fois par jour. 26 h de silence sont normales pour l'une, une panne pour
 * l'autre. `*` = toutes les heures ; `6,18` = 12 h ; `13` = 24 h. */
export function intervalleAttenduH(cronHour: string): number {
  if (cronHour.trim() === "*") return 1;
  const heures = cronHour
    .split(",")
    .map((h) => Number.parseInt(h, 10))
    .filter((h) => Number.isInteger(h) && h >= 0 && h <= 23)
    .sort((a, b) => a - b);
  if (heures.length === 0) return 24;
  let ecartMax = 24 - heures[heures.length - 1] + heures[0];
  for (let i = 1; i < heures.length; i++) {
    ecartMax = Math.max(ecartMax, heures[i] - heures[i - 1]);
  }
  return ecartMax;
}

export function evaluerTache(tache: ScheduleApi, maintenant: number): EtatTache {
  const intervalleH = intervalleAttenduH(tache.cron_hour);
  if (!tache.enabled) return { tache, niveau: "suspendue", intervalleH };
  if (!tache.last_run_at) return { tache, niveau: "jamais", intervalleH };
  if (tache.last_status === "error") return { tache, niveau: "erreur", intervalleH };
  const ecartH = (maintenant - new Date(tache.last_run_at).getTime()) / 3_600_000;
  if (ecartH > intervalleH + MARGE_H) return { tache, niveau: "retard", intervalleH };
  return { tache, niveau: "ok", intervalleH };
}

/** Panne = une tâche en erreur ou en retard (la chaîne ne tourne plus).
 * Attention = des sources en échec au dernier passage (la chaîne tourne, mais
 * sans une partie de sa matière). Une tâche SUSPENDUE est un réglage
 * volontaire, jamais une panne — même doctrine que le statut `skipped`. */
export function etatGlobal(taches: EtatTache[], sourcesEnEchec: number): NiveauGlobal {
  if (taches.some((t) => t.niveau === "erreur" || t.niveau === "retard")) return "panne";
  if (sourcesEnEchec > 0) return "attention";
  return "ok";
}

export const LIBELLE_NIVEAU: Record<NiveauTache, string> = {
  ok: "à l'heure",
  erreur: "en erreur",
  retard: "en retard",
  suspendue: "suspendue",
  jamais: "jamais exécutée",
};
