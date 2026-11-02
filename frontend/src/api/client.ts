import { tokenStorage } from "./tokenStorage";

// ⚠️ `import.meta.env` est typé `any` tant qu'aucune déclaration ne le décrit :
// sans annotation, l'adresse de l'API se propage en `any` dans tout le client.
const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Notifie l'AuthContext qu'un logout forcé est nécessaire (refresh token
 * lui-même invalide/expiré). Branché depuis AuthContext pour éviter une
 * dépendance circulaire module-level entre client.ts et le contexte React. */
let onSessionExpired: (() => void) | null = null;
export function registerSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshOnce(): Promise<boolean> {
  const refreshToken = tokenStorage.getRefreshToken();
  if (!refreshToken) return false;

  // Plusieurs requêtes en parallèle qui essuient un 401 ne doivent déclencher
  // qu'un seul appel /api/auth/refresh -- les suivantes attendent le même résultat.
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        // ⚠️ `res.json()` est typé `any` : sans annotation, les deux jetons
        // arrivent en `any` jusqu'au stockage de session — le point le plus
        // sensible de l'application.
        const body = (await res.json()) as {
          access_token: string;
          refresh_token: string;
        };
        tokenStorage.setTokens(body.access_token, body.refresh_token);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

/**
 * Corps d'erreur renvoyé par l'API (FastAPI met le message dans `detail`).
 *
 * ⚠️ `response.json()` est typé `any` par la bibliothèque DOM : sans ce type,
 * `body.detail` est un `any` qui se propage jusqu'au message affiché à
 * l'analyste. C'est la seule fuite de typage du client HTTP, au point le plus
 * central de l'application — invisible au grep parce qu'elle vient de la
 * plateforme, pas d'un `any` écrit à la main.
 */
interface ApiErrorBody {
  detail?: string;
}

async function request<T>(path: string, init?: RequestInit, isRetry = false): Promise<T> {
  const accessToken = tokenStorage.getAccessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init?.headers,
    },
  });

  // ⚠️ `/logout` aussi : un 401 sur la déconnexion (session déjà révoquée)
  // relancerait la déconnexion, qui rappellerait /logout — une boucle.
  const isAuthMutation =
    path === "/api/auth/login" || path === "/api/auth/refresh" || path === "/api/auth/logout";
  if (response.status === 401 && !isRetry && !isAuthMutation) {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      return request<T>(path, init, true);
    }
    tokenStorage.clear();
    onSessionExpired?.();
    throw new ApiError(401, "Session expirée, veuillez vous reconnecter.");
  }

  if (!response.ok) {
    const body = (await response
      .json()
      .catch(() => ({ detail: response.statusText }))) as ApiErrorBody;
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

/**
 * Télécharge un fichier servi par l'API, en conservant l'authentification.
 *
 * ⚠️ Un simple `<a href>` ne porterait PAS l'en-tête `Authorization` : le
 * navigateur ferait la requête hors du client HTTP de l'application et
 * recevrait un 401. On récupère donc le contenu ici, puis on déclenche le
 * téléchargement depuis un objet local.
 */
export async function downloadFile(
  path: string,
  fallbackName: string,
  isRetry = false,
): Promise<void> {
  const accessToken = tokenStorage.getAccessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });

  // ⚠️ MEME RATTRAPAGE DE SESSION QUE `request`. Sans lui, un téléchargement
  // lancé après expiration du jeton échouait sur « Token invalide ou expiré »
  // alors que le reste de l'application se renouvelle en silence — constaté à
  // l'usage sur le bouton « rapport PDF ». Un export ne doit pas être le seul
  // endroit où l'analyste est éjecté.
  if (response.status === 401 && !isRetry) {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      return downloadFile(path, fallbackName, true);
    }
    tokenStorage.clear();
    onSessionExpired?.();
    throw new ApiError(401, "Session expirée, veuillez vous reconnecter.");
  }

  if (!response.ok) {
    const body = (await response
      .json()
      .catch(() => ({ detail: response.statusText }))) as ApiErrorBody;
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  // Le serveur propose un nom via Content-Disposition ; on le respecte quand
  // il est là, l'analyste retrouvant ainsi la date dans le nom du fichier.
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const nom = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const lien = document.createElement("a");
  lien.href = url;
  lien.download = nom;
  document.body.appendChild(lien);
  lien.click();
  lien.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body ? JSON.stringify(body) : undefined }),
  delete: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
};
