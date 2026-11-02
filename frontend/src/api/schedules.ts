import { api } from "./client";

// Miroir de ScheduleOut / SchedulesResponse (backend/app/api/routers/schedules.py).
export interface ScheduleApi {
  id: string;
  label: string;
  action: string;
  action_label: string;
  // Imposée par l'action, jamais choisie ici : une tâche longue sur la file par
  // défaut bloquerait la collecte ET l'alerting.
  queue: string;
  cron_minute: string;
  cron_hour: string;
  cron_day_of_week: string;
  // Horaire tel que Celery Beat l'appliquera, en clair.
  schedule: string;
  enabled: boolean;
  last_run_at: string | null;
  // "success" | "error" | "skipped". `skipped` = tâche suspendue au moment où
  // Beat l'a déclenchée — à ne pas confondre avec un échec.
  last_status: string | null;
  last_duration_seconds: number | null;
  last_detail: string | null;
}

// Liste blanche côté serveur : l'interface ne propose que ces actions, et le
// serveur refuse tout ce qui n'y est pas.
export interface ScheduleActionApi {
  action: string;
  label: string;
  queue: string;
  description: string;
}

export interface SchedulesResponse {
  schedules: ScheduleApi[];
  actions: ScheduleActionApi[];
  // Délai maximal avant que Beat relise la base. Affiché tel quel : sans lui,
  // un changement sans effet immédiat passerait pour une panne.
  reload_delay_seconds: number;
}

export interface SchedulePayload {
  label: string;
  action: string;
  cron_minute: string;
  cron_hour: string;
  cron_day_of_week: string;
  enabled?: boolean;
}

export const schedulesApi = {
  list: () => api.get<SchedulesResponse>("/api/schedules"),
  create: (payload: SchedulePayload) =>
    api.post<ScheduleApi>("/api/schedules", payload),
  update: (id: string, payload: Partial<SchedulePayload>) =>
    api.patch<ScheduleApi>(`/api/schedules/${id}`, payload),
  remove: (id: string) => api.delete<void>(`/api/schedules/${id}`),
};
