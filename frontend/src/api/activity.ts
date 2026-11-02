import { api } from "./client";

// Miroir de ActiviteRecente (backend/app/api/routers/stats.py).
//
// ⚠️ Le tableau de bord comptait sans prioriser. Un analyste qui arrive le
// matin veut savoir ce qui a changé depuis hier et ce qui l'attend, pas la
// taille du corpus.
export interface ActivityApi {
  depuis: string;
  nouvelles_alertes: number;
  nouvelles_alertes_graves: number;
  nouveaux_documents: number;
  nouvelles_detections: number;
  alertes_ouvertes: number;
  alertes_non_affectees: number;
  alertes_sans_resume: number;
  // Trou structurel : une entité active sans sélecteur ne peut JAMAIS alerter.
  entites_sans_selecteur: number;
  sources_en_echec: number;
}

export const activityApi = {
  get: (heures = 24) => api.get<ActivityApi>(`/api/stats/activity?heures=${heures}`),
};
