import { api } from "./client";

export type LinkStatus =
  | "alive"
  | "gone"
  | "restricted"
  | "server_error"
  | "unreachable";

export interface LinkHealthItemApi {
  url: string;
  host: string;
  is_onion: boolean;
  status: LinkStatus;
  http_status: number | null;
  /** Titre de la page cible -- seule donnée de contenu remontée, suffisante
   * pour qualifier un lien sans rapatrier la page. */
  title: string | null;
  content_type: string | null;
  content_length: number | null;
}

export interface LinkHealthApi {
  documents_scanned: number;
  documents_with_links: number;
  hosts_checked: number;
  counts_by_status: Record<string, number>;
  alive_ratio: number | null;
  items: LinkHealthItemApi[];
}

export const linksApi = {
  check: (limitDocuments = 100) =>
    api.post<LinkHealthApi>(`/api/links/check?limit_documents=${limitDocuments}`),
};
