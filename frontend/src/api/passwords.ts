import { api } from "./client";

/** Résultat d'une passe de corroboration HIBP. Ne contient que des comptages
 * agrégés : jamais un mot de passe, jamais un hash, jamais la liste des
 * credentials concernés (voir backend pipeline/enrich/hibp.py). */
export interface PasswordBreachApi {
  documents_scanned: number;
  credentials_found: number;
  unique_passwords: number;
  passwords_checked: number;
  breached_count: number;
  unknown_count: number;
  lookup_errors: number;
  /** null si rien n'a été vérifié -- "aucune mesure" n'est pas "aucun compromis". */
  breached_ratio: number | null;
  /** Répartition par tranche d'apparitions : "100k+" = recyclage massif,
   * "1-10" = mot de passe rare, signal bien plus fort. */
  breach_buckets: Record<string, number>;
}

export const passwordsApi = {
  checkBreaches: (limitDocuments = 100) =>
    api.post<PasswordBreachApi>(
      `/api/passwords/check-breaches?limit_documents=${limitDocuments}`,
    ),
};
