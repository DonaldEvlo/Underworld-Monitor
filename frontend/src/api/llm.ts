import { api } from "./client";

export interface LLMOption {
  id: string;
  provider: string;
  label: string;
  available: boolean;
}

export interface LLMSelection {
  model: string;
}

export interface AnalyzeResult {
  response: string;
}

export const llmApi = {
  options: () => api.get<LLMOption[]>("/api/llm/options"),
  getSelected: () => api.get<LLMSelection>("/api/llm/select"),
  select: (model: string) => api.post<LLMSelection>("/api/llm/select", { model }),
  analyze: (content: string, query: string) =>
    api.post<AnalyzeResult>("/api/llm/analyze", { content, query }),
  analyzeBatch: (batchId: string, query: string) =>
    api.post<AnalyzeResult>("/api/llm/analyze-batch", { batch_id: batchId, query }),
};
