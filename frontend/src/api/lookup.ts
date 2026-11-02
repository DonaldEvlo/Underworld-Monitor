import { api } from "./client";

// Miroir de LookupResponse (backend/app/api/routers/lookup.py).
//
// ⚠️ À ne pas confondre avec `search.ts` : celui-ci cherche de NOUVELLES
// SOURCES sur des moteurs .onion, celui-là cherche dans le corpus déjà
// collecté — le geste qu'un analyste fait vingt fois par jour.
export interface LookupEntity {
  id: string;
  name: string;
  active: boolean;
  matched_selector: string | null;
}

export interface LookupAlert {
  id: string;
  subject: string;
  severity: string;
  status: string;
  alert_date: string;
  corroboration_status: string | null;
}

export interface LookupDetection {
  id: string;
  type: string;
  value_masked: string;
  severity: string | null;
  corroboration_status: string | null;
  corroborated_group: string | null;
  document_id: string;
  document_title: string | null;
  source_name: string | null;
  created_at: string;
}

export interface LookupDocument {
  id: string;
  title: string | null;
  source_name: string | null;
  url: string | null;
  published_at: string | null;
  fetched_at: string | null;
}

export interface LookupResponse {
  query: string;
  entities: LookupEntity[];
  alerts: LookupAlert[];
  detections: LookupDetection[];
  documents: LookupDocument[];
  // Totaux RÉELS avant troncature : « 21 (3 affichées) » est honnête,
  // « 3 » ne l'est pas.
  total_detections: number;
  total_documents: number;
  total_alerts: number;
}

export const lookupApi = {
  search: (q: string) =>
    api.get<LookupResponse>(`/api/lookup?q=${encodeURIComponent(q)}`),
};
