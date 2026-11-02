import { api } from "./client";

export interface DreadSearchHit {
  title: string;
  link: string;
  subdread: string | null;
  author: string | null;
  date: string | null;
  snippet: string | null;
}

export interface DreadKeywordResult {
  keyword: string;
  success: boolean;
  hits: DreadSearchHit[];
  error: string | null;
}

export interface DreadSearchJobStatus {
  job_id: string;
  status: "running" | "done";
  total: number;
  done: number;
  items: DreadKeywordResult[];
}

export const dreadSearchApi = {
  run: () => api.post<DreadSearchJobStatus>("/api/dread-search/run"),
  getStatus: (jobId: string) => api.get<DreadSearchJobStatus>(`/api/dread-search/${jobId}/status`),
};
