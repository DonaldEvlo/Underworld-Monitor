import type { AlertApi, AlertEvidenceResponse } from "../../../api/alerts";
import type { EntityApi } from "../../../api/entities";
import { detectionTypeLabels } from "../../../lib/taxonomy";

/** Ce que le dossier d'une alerte calcule UNE fois et que ses sections lisent.
 *
 * ⚠️ Le dossier tenait en un seul composant de 880 lignes. Découpé en
 * sections, il garde un seul endroit où ces valeurs sont DÉRIVÉES : les
 * sections les affichent, elles ne les recalculent pas.
 */
export interface ContexteDossier {
  alerte: AlertApi;
  sujet: string;
  domaine: string | null;
  enCours: string | null;
  telecharger: (nom: string, action: () => Promise<void>) => Promise<void>;
  agir: (nom: string, action: () => Promise<AlertApi>) => Promise<void>;
  confirmee: boolean;
  exclusive: boolean;
  sansObjet: boolean;
  autresGroupes: string[];
  observateurs: string[];
  expositionMesuree: boolean;
  documents: AlertEvidenceResponse["documents"];
  documentPrincipal: AlertEvidenceResponse["documents"][number] | null;
  avance: string | null;
  preuves: AlertEvidenceResponse | null;
  entitesParId: Record<string, EntityApi>;
}

export function libelleType(type: string): string {
  return detectionTypeLabels[type as keyof typeof detectionTypeLabels] ?? type;
}
