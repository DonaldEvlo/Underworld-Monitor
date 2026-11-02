import { api } from "./client";

// Miroir de DocumentListItem/DocumentListResponse/DocumentDetail (backend/app/api/routers/documents.py)
export interface DocumentListItem {
  id: string;
  source_id: string;
  source_name: string | null;
  url: string;
  content_preview: string;
  title: string | null;
  author: string | null;
  source_type: string;
  collector: string;
  published_at: string | null;
  fetched_at: string;
  is_duplicate: boolean;
  matched_keywords: string[] | null;
  mentioned_url_count: number;
  content_locked: boolean;
  // Verdict du classifieur d'annonces (backend detect/announcement_filter.py).
  // `null` sur un document anterieur au classement.
  announcement_class: AnnouncementClass | null;
  announcement_reason: string | null;
}

// Miroir de AnnouncementClass (backend). `uncertain` n'est PAS un demi-bruit :
// c'est ce que les regles n'ont pas su trancher, et il ne doit jamais etre
// masque avec le bruit.
export type AnnouncementClass = "leak" | "uncertain" | "noise";

export interface DocumentListResponse {
  total: number;
  offset: number;
  limit: number;
  items: DocumentListItem[];
}

export interface DocumentDetail {
  id: string;
  source_id: string;
  source_name: string | null;
  url: string;
  content: string;
  content_hash: string;
  title: string | null;
  author: string | null;
  source_type: string;
  collector: string;
  collector_version: string;
  published_at: string | null;
  fetched_at: string;
  raw_html: string | null;
  source_meta: Record<string, unknown> | null;
  is_duplicate: boolean;
  matched_keywords: string[] | null;
}

// Miroir de DocumentSortBy/SortOrder (backend/app/repositories/document_repo.py)
export type DocumentSortBy =
  | "relevance"
  | "freshness"
  | "fetched_at"
  | "published_at"
  | "title";
export type SortOrder = "asc" | "desc";

export interface DocumentListParams {
  source_id?: string;
  collector?: string;
  q?: string;
  only_matched?: boolean;
  announcement_class?: AnnouncementClass[];
  fetched_from?: string;
  fetched_to?: string;
  sort_by?: DocumentSortBy;
  sort_order?: SortOrder;
  offset?: number;
  limit?: number;
}

function buildQuery(params: DocumentListParams): string {
  const search = new URLSearchParams();
  if (params.source_id) search.set("source_id", params.source_id);
  if (params.collector) search.set("collector", params.collector);
  if (params.q) search.set("q", params.q);
  if (params.only_matched) search.set("only_matched", "true");
  // Repetable cote API : une valeur par verdict retenu.
  for (const cls of params.announcement_class ?? [])
    search.append("announcement_class", cls);
  if (params.fetched_from) search.set("fetched_from", params.fetched_from);
  if (params.fetched_to) search.set("fetched_to", params.fetched_to);
  if (params.sort_by) search.set("sort_by", params.sort_by);
  if (params.sort_order) search.set("sort_order", params.sort_order);
  search.set("offset", String(params.offset ?? 0));
  search.set("limit", String(params.limit ?? 50));
  return search.toString();
}

export interface DeleteAllResponse {
  deleted_count: number;
  deleted_detections_count: number;
}

export type TranslationTargetLang = "fr" | "en";

export interface TranslateResponse {
  source_lang: string;
  target_lang: TranslationTargetLang;
  translated_title: string | null;
  translated_content: string;
}

export interface DocumentSummaryResponse {
  document_id: string;
  model: string;
  summary: string;
  content_length: number;
  submitted_length: number;
}

export const documentsApi = {
  list: (params: DocumentListParams = {}) => api.get<DocumentListResponse>(`/api/documents?${buildQuery(params)}`),
  get: (id: string) => api.get<DocumentDetail>(`/api/documents/${id}`),
  deleteAll: () => api.delete<DeleteAllResponse>("/api/documents"),
  // Résumé LLM d'un document. Le serveur BORNE le texte soumis : un document
  // du corpus fait 735 797 caractères, l'envoyer entier saturerait la fenêtre
  // de contexte du modèle. L'écart entre `content_length` et
  // `submitted_length` doit rester visible à l'écran.
  summarize: (id: string) =>
    api.post<DocumentSummaryResponse>(`/api/documents/${id}/summarize`, {}),
  translate: (id: string, targetLang: TranslationTargetLang) =>
    api.post<TranslateResponse>(`/api/documents/${id}/translate`, { target_lang: targetLang }),
};
