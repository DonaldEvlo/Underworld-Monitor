import { api } from "./client";

export interface UserApi {
  id: string;
  username: string;
  /** `analyst` | `admin` | `viewer` — miroir de core/roles.py.
   *
   * ⚠️ SERT UNIQUEMENT À L'AFFICHAGE. La garde réelle est SERVEUR
   * (`api/deps.exige_role`) : masquer une entrée de menu n'est pas une mesure
   * de sécurité, c'est une mesure d'honnêteté — ne pas promettre à un RSSI
   * des pages dont chaque appel répondrait 403. Ne jamais s'en servir comme
   * seul rempart. */
  role: string;
  active: boolean;
  created_at: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export const authApi = {
  login: (username: string, password: string) => api.post<TokenPair>("/api/auth/login", { username, password }),
  refresh: (refresh_token: string) => api.post<TokenPair>("/api/auth/refresh", { refresh_token }),
  me: () => api.get<UserApi>("/api/auth/me"),
  // Révoque la session CÔTÉ SERVEUR : ses jetons ne servent plus, sur aucun
  // onglet. "idle" = déconnexion pour inactivité (motif tracé).
  logout: (reason: "logout" | "idle" = "logout") => api.post<void>("/api/auth/logout", { reason }),
  // Signal d'activité : garde la session vivante pendant une lecture sans appel.
  heartbeat: () => api.post<void>("/api/auth/heartbeat"),
};
