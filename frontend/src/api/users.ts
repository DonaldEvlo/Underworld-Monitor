import { api } from "./client";

/** Miroir de `UserOut` (backend/app/api/routers/users.py).
 *
 * ⚠️ NE PORTE PAS `password_hash` — et ne doit jamais le porter. Le contrat
 * serveur l'exclut champ par champ, verrouillé par test. */
export interface UserApi {
  id: string;
  username: string;
  /** `analyst` | `admin` | `viewer` */
  role: string;
  active: boolean;
  created_at: string;
}

export interface CreateUserInput {
  username: string;
  password: string;
  role: string;
}

export interface UpdateUserInput {
  role?: string;
  active?: boolean;
  password?: string;
}

/** Avis HIBP sur un mot de passe candidat.
 *
 * ⚠️ `unavailable` distingue « non compromis » de « pas pu vérifier ». Une
 * absence de mesure n'est pas un résultat rassurant — même convention que
 * `corroboration_status` null. */
export interface PasswordAdvice {
  breached: boolean;
  breach_count: number;
  unavailable: boolean;
}

export const usersApi = {
  list: () => api.get<UserApi[]>("/api/users"),
  create: (payload: CreateUserInput) => api.post<UserApi>("/api/users", payload),
  update: (id: string, payload: UpdateUserInput) =>
    api.patch<UserApi>(`/api/users/${id}`, payload),
  remove: (id: string) => api.delete<void>(`/api/users/${id}`),
  /** ⚠️ Le mot de passe candidat part au serveur, qui n'en transmet que les
   * 5 premiers caractères du SHA-1 à HIBP (k-anonymity) et ne le persiste
   * jamais. Voir `pipeline/enrich/hibp.py`. */
  passwordAdvice: (password: string) =>
    api.post<PasswordAdvice>("/api/users/password-advice", { password }),
};
