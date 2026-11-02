import { api } from "./client";

/** Miroir de `LoginOut` (backend/app/api/routers/telegram.py). */
export type LoginPhase =
  | "idle"
  | "starting"
  | "waiting_scan"
  | "password_needed"
  | "connected"
  | "expired"
  | "cancelled"
  | "error";

export interface TelegramLogin {
  phase: LoginPhase;
  /** QR à scanner, en SVG — présent seulement tant qu'il est valide. */
  qr_svg: string | null;
  qr_expires_at: string | null;
  message: string | null;
  via_tor: boolean;
  password_attempts_left: number;
}

/** Miroir de `StatusOut`.
 *
 * ⚠️ `authorized: null` signifie « pas vérifié », jamais « non connecté » —
 * même convention que `corroboration_status` null. */
export interface TelegramStatus {
  api_configured: boolean;
  /** Dernière connexion connue réussie. ⚠️ Le fichier de session seul ne
   * prouve rien : Telethon le crée dès la première tentative, même ratée. */
  connected: boolean;
  authorized: boolean | null;
  login: TelegramLogin;
}

export const PHASES_ACTIVES: LoginPhase[] = ["starting", "waiting_scan", "password_needed"];

export const telegramApi = {
  status: (check = false) =>
    api.get<TelegramStatus>(`/api/telegram/status${check ? "?check=true" : ""}`),
  startLogin: (sansTor: boolean) =>
    api.post<TelegramLogin>("/api/telegram/login", { sans_tor: sansTor }),
  login: () => api.get<TelegramLogin>("/api/telegram/login"),
  /** ⚠️ Le mot de passe de vérification en deux étapes part au serveur, qui
   * le transmet à Telegram puis l'oublie : jamais journalisé ni conservé. */
  password: (password: string) =>
    api.post<TelegramLogin>("/api/telegram/login/password", { password }),
  cancel: () => api.post<TelegramLogin>("/api/telegram/login/cancel"),
  logout: () => api.post<void>("/api/telegram/logout"),
};
