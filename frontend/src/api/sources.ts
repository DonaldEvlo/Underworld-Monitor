import { api } from "./client";
import type { SourceType } from "../types/domain";

// Miroir de `SourceContract` (backend/app/contracts/source.py)
export interface SourceApi {
  id: string;
  name: string;
  type: SourceType;
  url: string;
  active: boolean;
  requires_js: boolean;
  last_collected_at: string | null;
  created_at: string;
}

export interface SourceCreatePayload {
  name: string;
  type: SourceType;
  url: string;
  active?: boolean;
  requires_js?: boolean;
}

export interface SourceUpdatePayload {
  name?: string;
  type?: SourceType;
  url?: string;
  active?: boolean;
  requires_js?: boolean;
}

// Miroir de `SourceExportEnvelope` / `SourceImportResult` (backend/app/api/routers/sources.py)
export interface SourceExportItem {
  name: string;
  type: SourceType;
  url: string;
  active: boolean;
  requires_js: boolean;
}

export interface SourceExportEnvelope {
  format: string;
  exported_at: string;
  count: number;
  sources: SourceExportItem[];
}

export interface SourceImportResult {
  created: number;
  skipped: number;
  errors: { name: string; reason: string }[];
}

export interface CollectResult {
  success: boolean;
  title?: string | null;
  text?: string | null;
  text_length?: number | null;
  matched_keywords?: string[];
  error?: string | null;
  saved_count: number;
  collector?: string | null;
}

export interface BatchItem {
  source_id: string;
  name: string;
  success: boolean;
  text_length?: number | null;
  text_preview?: string | null;
  matched_keywords?: string[];
  error?: string | null;
  saved_count: number;
  collector?: string | null;
  duration_seconds: number | null;
}

export interface BatchJobStatus {
  batch_id: string;
  status: "running" | "done";
  total: number;
  done: number;
  items: BatchItem[];
  // Temps restant estimé, en secondes. `null` tant qu'aucune durée passée
  // n'est connue — on préfère ne rien afficher qu'un chiffre inventé.
  eta_seconds: number | null;
  // Sur combien de sources l'estimation repose réellement. À afficher avec
  // elle : une estimation bâtie sur 1 source connue sur 24 ne vaut pas celle
  // bâtie sur 24, et le lecteur doit pouvoir en juger.
  eta_known_sources: number;
  eta_total_sources: number;
}

// Miroir de GithubImportJobStatus (backend/app/api/routers/sources.py)
export interface GithubImportCreatedSource {
  name: string;
  url: string;
  http_status: number | null;
}

export interface GithubImportJobStatus {
  job_id: string;
  status: "fetching" | "testing" | "done" | "error";
  total_parsed: number;
  new_candidates: number;
  tested: number;
  created: GithubImportCreatedSource[];
  unreachable: number;
  error: string | null;
}

export interface SourceHealthItem {
  source_id: string;
  name: string;
  url: string;
  active: boolean;
  requires_js: boolean;
  reachable: boolean;
  http_status: number | null;
  checked_at: string;
}

export interface SourceHealthReport {
  checked: number;
  reachable: number;
  unreachable: number;
  reachable_ratio: number;
  items: SourceHealthItem[];
}

// Miroir de SourceTestJobStatus (backend/app/api/routers/sources.py).
// Test de disponibilité en tâche de fond : l'état vit côté serveur, il
// survit à un changement de page comme à un rechargement de l'onglet.
export type SourceTestState = "pending" | "reachable" | "unreachable" | "retrying" | "untested";

export interface SourceTestEntry {
  source_id: string;
  name: string;
  url: string;
  active: boolean;
  requires_js: boolean;
  state: SourceTestState;
  http_status: number | null;
  checked_at: string | null;
  // Dernière collecte RÉUSSIE (jamais écrite sur un échec). Fait foi quand le
  // test n'est pas concluant : source qui exige un navigateur.
  last_collected_at: string | null;
}

export interface SourceTestJob {
  job_id: string;
  status: "running" | "done" | "error";
  scope: "active" | "all" | "one";
  phase: "first_pass" | "retry" | "done";
  total: number;
  first_pass_done: number;
  // Seconde passe : uniquement les échecs, après renouvellement du circuit Tor.
  retry_total: number;
  retry_done: number;
  reachable: number;
  unreachable: number;
  entries: SourceTestEntry[];
  started_at: string;
  updated_at: string;
  finished_at: string | null;
  error: string | null;
}

// Miroir de AddressChangeOut (backend/app/api/routers/source_addresses.py).
// `applied` = la source a basculé ; `pending` = repérée, pas prouvée ;
// `rejected` = écartée par un analyste, plus jamais reproposée.
export interface AddressChangeApi {
  id: string;
  source_id: string;
  source_name: string;
  old_url: string;
  new_url: string;
  origin: "site" | "deepdarkcti";
  status: "applied" | "pending" | "rejected";
  evidence: string | null;
  reason: string | null;
  parsed_victims: number | null;
  common_victims: number | null;
  detected_at: string;
  last_checked_at: string;
  applied_at: string | null;
  decided_by: string | null;
}

export const addressChangesApi = {
  list: () => api.get<AddressChangeApi[]>("/api/source-addresses"),
  run: (origin: "site" | "deepdarkcti") =>
    api.post<{ task_id: string; origin: string }>(`/api/source-addresses/run?origin=${origin}`),
  apply: (id: string) => api.post<AddressChangeApi>(`/api/source-addresses/${id}/apply`),
  reject: (id: string) => api.post<AddressChangeApi>(`/api/source-addresses/${id}/reject`),
};

export const sourcesApi = {
  startTestJob: (payload: { only_active?: boolean; source_id?: string }) =>
    api.post<SourceTestJob>("/api/sources/test-jobs", payload),
  getTestJob: (jobId: string) => api.get<SourceTestJob>(`/api/sources/test-jobs/${jobId}`),
  getLatestTestJob: () => api.get<SourceTestJob>("/api/sources/test-jobs/latest"),
  list: () => api.get<SourceApi[]>("/api/sources"),
  create: (payload: SourceCreatePayload) => api.post<SourceApi>("/api/sources", payload),
  update: (id: string, payload: SourceUpdatePayload) => api.patch<SourceApi>(`/api/sources/${id}`, payload),
  remove: (id: string) => api.delete(`/api/sources/${id}`),
  exportAll: () => api.get<SourceExportEnvelope>("/api/sources/export"),
  importAll: (envelope: SourceExportEnvelope) =>
    api.post<SourceImportResult>("/api/sources/import", envelope),
  collect: (id: string) => api.post<CollectResult>(`/api/sources/${id}/collect`),
  test: (id: string) => api.post<SourceHealthItem>(`/api/sources/${id}/test`),
  testAll: (onlyActive = false) =>
    api.post<SourceHealthReport>(`/api/sources/test?only_active=${onlyActive}`),
  startCollectAll: () => api.post<BatchJobStatus>("/api/sources/collect-all"),
  getCollectAllStatus: (batchId: string) =>
    api.get<BatchJobStatus>(`/api/sources/collect-all/${batchId}/status`),
  startGithubImport: () => api.post<GithubImportJobStatus>("/api/sources/import-github"),
  getGithubImportStatus: (jobId: string) =>
    api.get<GithubImportJobStatus>(`/api/sources/import-github/${jobId}/status`),
};
