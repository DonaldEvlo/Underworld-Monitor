import { api } from "./client";
import type { AlertSeverity, AlertStatus } from "../types/domain";

// Miroir de pipeline/reporting/perimeter.py. ⚠️ Faits de SYNTHÈSE seulement :
// ni détection, ni valeur, ni document — c'est la vue du RSSI.

export type PerimeterState =
  | "inactive"
  | "aveugle"
  | "a_traiter"
  | "en_cours"
  | "traitee"
  | "aucune_alerte";

export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
}

export interface PerimeterOrg {
  id: string;
  name: string;
  country: string | null;
  sector: string | null;
  sector_label: string | null;
  sector_critical: boolean;
  state: PerimeterState;
  open_by_severity: SeverityCounts;
  open_total: number;
  alerts_total: number;
  last_alert_date: string | null;
  last_alert_severity: AlertSeverity | null;
}

export interface PerimeterGroup extends PerimeterOrg {
  subsidiaries: PerimeterOrg[];
  group_open_by_severity: SeverityCounts;
  group_open_total: number;
}

export interface PerimeterResponse {
  organizations: number;
  groups_with_subsidiaries: number;
  to_handle: number;
  blind: number;
  groups: PerimeterGroup[];
}

export interface PerimeterAlert {
  id: string;
  alert_date: string;
  severity: AlertSeverity;
  status: AlertStatus;
  credibility_level: string | null;
  summary: string | null;
  resolution_reason: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  organization: string | null;
}

export interface PerimeterAlertsResponse {
  entity_id: string;
  name: string;
  alerts: PerimeterAlert[];
}

export const perimeterApi = {
  get: () => api.get<PerimeterResponse>("/api/perimeter"),
  alerts: (entityId: string) =>
    api.get<PerimeterAlertsResponse>(`/api/perimeter/${entityId}/alerts`),
};
