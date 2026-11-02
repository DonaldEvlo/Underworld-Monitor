import { api } from "./client";

// Miroir de DetectionListItem/DetectionListResponse (backend/app/api/routers/detections.py)
export interface DetectionListItem {
  id: string;
  document_id: string;
  document_title: string | null;
  document_url: string | null;
  document_collector: string | null;
  // Rubrique declaree par la source pour le document d'origine (voir
  // backend/app/pipeline/detect/patterns/topic.py) -- contexte de publication.
  document_topic: string | null;
  type: string;
  value_masked: string;
  validated: boolean;
  is_relevant: boolean;
  // Corroboration par victime (RansomLook). `not_applicable` = mention de
  // forum ou infrastructure ; null = jamais confrontée.
  corroboration_status: string | null;
  corroborated_group: string | null;
  corroborated_groups: string[] | null;
  corroboration_match: "domain" | "name" | null;
  corroboration_first_seen_at: string | null;
  corroboration_observers: string[] | null;
  created_at: string;
}

export interface DetectionListResponse {
  total: number;
  offset: number;
  limit: number;
  counts_by_type: Record<string, number>;
  relevant_count: number;
  items: DetectionListItem[];
}

// Miroir de DetectionSortBy/SortOrder (backend/app/repositories/detection_repo.py)
export type DetectionSortBy = "created_at" | "type" | "value_masked";
export type SortOrder = "asc" | "desc";

export interface DetectionListParams {
  // Recherche dans la valeur MASQUÉE — la seule que l'on conserve.
  q?: string;
  type?: string;
  validated?: boolean;
  isRelevant?: boolean;
  createdFrom?: string;
  createdTo?: string;
  sortBy?: DetectionSortBy;
  sortOrder?: SortOrder;
  offset?: number;
  limit?: number;
}

function buildQuery(params: DetectionListParams): string {
  const recherche = params.q?.trim();
  const search = new URLSearchParams();
  if (params.type) search.set("type", params.type);
  if (params.validated !== undefined) search.set("validated", String(params.validated));
  if (params.isRelevant !== undefined) search.set("is_relevant", String(params.isRelevant));
  if (params.createdFrom) search.set("created_from", params.createdFrom);
  if (params.createdTo) search.set("created_to", params.createdTo);
  if (params.sortBy) search.set("sort_by", params.sortBy);
  if (params.sortOrder) search.set("sort_order", params.sortOrder);
  search.set("offset", String(params.offset ?? 0));
  search.set("limit", String(params.limit ?? 50));
  if (recherche) search.set("q", recherche);
  return search.toString();
}

export interface IntelXDetectionCorroboration {
  domain: string;
  hit_count: number;
  /** true = plafond IntelX atteint : lire "au moins N", jamais "N". */
  is_truncated?: boolean;
  buckets: Record<string, number>;
}

export const detectionsApi = {
  list: (params: DetectionListParams = {}) => api.get<DetectionListResponse>(`/api/detections?${buildQuery(params)}`),
  corroborateIntelx: (detectionId: string) =>
    api.post<IntelXDetectionCorroboration>(`/api/detections/${detectionId}/corroborate-intelx`),
};
