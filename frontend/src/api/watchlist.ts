import { api } from "./client";

export interface KeywordApi {
  id: string;
  term: string;
  active: boolean;
  created_at: string;
}

export interface KeywordCreatePayload {
  term: string;
  active?: boolean;
}

export interface KeywordUpdatePayload {
  term?: string;
  active?: boolean;
}

export const watchlistApi = {
  list: () => api.get<KeywordApi[]>("/api/watchlist"),
  create: (payload: KeywordCreatePayload) => api.post<KeywordApi>("/api/watchlist", payload),
  update: (id: string, payload: KeywordUpdatePayload) => api.patch<KeywordApi>(`/api/watchlist/${id}`, payload),
  remove: (id: string) => api.delete(`/api/watchlist/${id}`),
};
