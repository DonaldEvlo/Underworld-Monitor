import { api } from "./client";
import type { DocumentListItem } from "./documents";

export type SelectorType = "domain" | "email_domain" | "keyword";
export type VerificationMethod = "dns_txt" | "manual";
export type VerificationStatus = "pending" | "verified" | "failed";

export interface SelectorApi {
  id: string;
  type: SelectorType;
  value: string;
}

export interface EntityApi {
  id: string;
  name: string;
  active: boolean;
  selectors: SelectorApi[];
  // ⚠️ false = entité active SANS aucun sélecteur : elle ne peut
  // structurellement jamais alerter (matching.py ne compare que des
  // sélecteurs). 8 entités sur 42 étaient dans ce cas le 2026-09-04.
  can_alert: boolean;
  verification_method: VerificationMethod | null;
  verification_status: VerificationStatus;
  verified_at: string | null;
  created_at: string;
  // Groupe et filiales (migration 0033) : un seul niveau. Pays (ISO2) et
  // secteur DÉCLARÉS priment sur ce qu'en dit le tiers (ransomware.live).
  parent_id: string | null;
  country: string | null;
  sector: string | null;
}

export interface SectorOption {
  value: string;
  label: string;
  // Secteur critique au sens NIS2 : élève la gravité.
  critical: boolean;
}

export interface SelectorInput {
  type: SelectorType;
  value: string;
}

export interface EntityCreatePayload {
  name: string;
  active?: boolean;
  selectors?: SelectorInput[];
  parent_id?: string | null;
  country?: string | null;
  sector?: string | null;
}

export interface EntityUpdatePayload {
  name?: string;
  active?: boolean;
  selectors?: SelectorInput[];
  verification_method?: VerificationMethod;
  verification_status?: VerificationStatus;
  // `null` explicite = retirer (le serveur distingue absent et null).
  parent_id?: string | null;
  country?: string | null;
  sector?: string | null;
}

export interface SubdomainDiscoveryResult {
  queried_domains: string[];
  discovered: string[];
}

export interface IntelXCorroborationOut {
  domain: string;
  hit_count: number;
  /** true = plafond IntelX atteint : lire "au moins N", jamais "N". */
  is_truncated?: boolean;
  buckets: Record<string, number>;
}

export interface IntelXCorroborationResult {
  results: IntelXCorroborationOut[];
}

export interface OrganizationCandidate {
  name: string;
  count: number;
}

export interface OrganizationBackfillJobStatus {
  job_id: string;
  status: "running" | "done" | "error";
  total: number;
  done: number;
  created_count: number;
  error: string | null;
}

export interface EntityDocumentsResponse {
  total: number;
  offset: number;
  limit: number;
  items: DocumentListItem[];
}

export const entitiesApi = {
  list: () => api.get<EntityApi[]>("/api/entities"),
  sectors: () => api.get<SectorOption[]>("/api/entities/sectors"),
  create: (payload: EntityCreatePayload) => api.post<EntityApi>("/api/entities", payload),
  update: (id: string, payload: EntityUpdatePayload) => api.patch<EntityApi>(`/api/entities/${id}`, payload),
  remove: (id: string) => api.delete(`/api/entities/${id}`),
  discoverSubdomains: (id: string) =>
    api.post<SubdomainDiscoveryResult>(`/api/entities/${id}/discover-subdomains`),
  corroborateIntelx: (id: string) =>
    api.post<IntelXCorroborationResult>(`/api/entities/${id}/corroborate-intelx`),
  listCandidates: () => api.get<OrganizationCandidate[]>("/api/entities/candidates"),
  candidateDocuments: (name: string, offset = 0, limit = 50) =>
    api.get<EntityDocumentsResponse>(
      `/api/entities/candidates/documents?name=${encodeURIComponent(name)}&offset=${offset}&limit=${limit}`,
    ),
  filterCandidatesWithLlm: (names: string[]) =>
    api.post<{ kept: string[] }>("/api/entities/candidates/filter-with-llm", { names }),
  startOrganizationBackfill: () =>
    api.post<OrganizationBackfillJobStatus>("/api/entities/backfill-organizations"),
  getBackfillStatus: (jobId: string) =>
    api.get<OrganizationBackfillJobStatus>(`/api/entities/backfill-organizations/${jobId}/status`),
  listDocuments: (id: string, offset = 0, limit = 20) =>
    api.get<EntityDocumentsResponse>(`/api/entities/${id}/documents?offset=${offset}&limit=${limit}`),
};
