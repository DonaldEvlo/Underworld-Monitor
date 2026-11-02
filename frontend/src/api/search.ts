import { api } from "./client";

export interface SearchCandidate {
  title: string;
  link: string;
  engine: string;
}

export interface SearchResponse {
  refined_query: string;
  candidates: SearchCandidate[];
}

export interface SearchPayload {
  query: string;
  model?: string;
}

export const searchApi = {
  search: (payload: SearchPayload) => api.post<SearchResponse>("/api/search", payload),
};
