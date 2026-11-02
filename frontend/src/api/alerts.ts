import { api, downloadFile } from "./client";
import type { AlertSeverity, AlertStatus } from "../types/domain";

// Miroir de AlertOut (backend/app/api/routers/alerts.py)
export interface AlertApi {
  id: string;
  // `null` pour une alerte de périmètre géographique : elle signale une
  // victime que personne n'a déclarée.
  entity_id: string | null;
  scope: "entity" | "region";
  // Continent surveillé, renseigné uniquement quand `scope === "region"`.
  region: string | null;
  severity: AlertSeverity;
  status: AlertStatus;
  alert_date: string;
  summary: string | null;
  detection_count: number;
  created_at: string;

  // Corroboration par un second observateur (RansomLook).
  // ⚠️ `null` = jamais confrontée : une ABSENCE DE MESURE, pas un résultat
  // négatif. Ne jamais l'afficher comme « non corroborée ».
  corroboration_status: string | null;
  corroborated_group: string | null;
  corroborated_count: number;
  // Tous les gangs qui revendiquent la victime (le premier = celui retenu).
  // Une double revendication est une information, pas un doublon.
  corroborated_groups: string[] | null;
  // Date d'indexation la plus ancienne chez un observateur : mesure notre
  // avance (ou notre retard) sur l'agrégateur.
  corroboration_first_seen_at: string | null;
  // Observateurs tiers ayant vu la victime (« ransomlook », « ransomware_live »).
  // Leur union augmente la couverture ; ce ne sont PAS des gangs.
  corroboration_observers: string[] | null;
  corroborated_at: string | null;
  // Preuve publique citable, propre à CETTE victime (capture de l'annonce du
  // gang). À distinguer de l'URL du document d'origine, qui est un .onion
  // exigeant Tor.
  corroboration_evidence_url: string | null;

  reminded_at: string | null;
  reminder_count: number;

  // --- Renseignements sur la victime (migration 0026) ---------------
  // ⚠️ AUCUNE PII : uniquement des COMPTEURS, des DATES et des LIBELLES.
  // ⚠️ Tout ceci ne veut rien dire tant que `intel_refreshed_at` est null :
  // `compromised_employees === 0` se lit « mesuré, et nul », `null` se lit
  // « jamais mesuré ». Ne jamais afficher « 0 exposition » sans mesure.
  victim_attack_date: string | null;
  victim_sector: string | null;
  victim_country: string | null;
  compromised_employees: number | null;
  compromised_users: number | null;
  compromised_thirdparties: number | null;
  // Familles de logiciel voleur (RedLine, Lumma...) : de la MÉTHODE au niveau
  // de l'organisation, pas un opérateur ni une personne.
  stealer_families: string[] | null;
  last_employee_compromised: string | null;
  last_user_compromised: string | null;
  intel_refreshed_at: string | null;

  // --- Confirmation par la presse (migration 0030) ------------------
  // Signal de CRÉDIBILITÉ (« la fuite est-elle réelle ? »), distinct de la
  // corroboration (« notre lecture est-elle juste ? »). `null` = aucune
  // confirmation connue, JAMAIS « fuite fausse » : la presse couvre surtout
  // les grandes organisations, et avec retard.
  press_source_url: string | null;
  press_evidence_url: string | null;
  press_confirmed_at: string | null;

  // --- Crédibilité (migration 0031) ---------------------------------
  // « La fuite est-elle réelle ? », axe DISTINCT de `severity`. `null` =
  // jamais évaluée. Toujours affichée AVEC sa preuve.
  credibility_level: string | null;
  credibility_evidence: string | null;
  credibility_assessed_at: string | null;

  // --- Notation Admiralty (calculée à la volée, jamais stockée) --------
  // Lettre A-F = fiabilité de la SOURCE (son historique mesuré), chiffre
  // 1-6 = crédibilité de l'INFORMATION. Chaque note porte son motif.
  admiralty_code: string | null;
  admiralty_source: string | null;
  admiralty_source_reason: string | null;
  admiralty_source_name: string | null;
  admiralty_information: string | null;
  admiralty_information_reason: string | null;
  /** Alerte RÉGIONALE : nomme la victime (titre du document publié par le
   * groupe). `null` pour une alerte d'entité, nommée par son entité. */
  subject_label: string | null;
  // La victime seule, sans « — victime non déclarée (région) » (liste).
  victim_label?: string | null;
  // Secteur traduit par le serveur (même table que la vue de direction).
  victim_sector_label?: string | null;

  // Travail d'analyste. `resolution_reason` distingue « faux positif écarté »
  // de « incident réel traité » — sans elle, l'historique des faux positifs
  // est perdu.
  assignee: string | null;
  analyst_note: string | null;
  resolution_reason: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;

  // --- Organisation et groupe (migration 0033) ----------------------
  entity_name?: string | null;
  group_id?: string | null;
  group_name?: string | null;

  // --- Corrections d'analyste (migration 0033) ----------------------
  // `severity`, `victim_country`, `victim_sector` portent la valeur
  // EFFECTIVE. `computed_*` = calcul de la plateforme, `*_override` =
  // décision d'analyste. Origine : "analyst" > "organization" > "computed".
  computed_severity?: AlertSeverity | null;
  computed_country?: string | null;
  computed_sector?: string | null;
  severity_override?: AlertSeverity | null;
  country_override?: string | null;
  sector_override?: string | null;
  override_reason?: string | null;
  override_by?: string | null;
  override_at?: string | null;
  severity_origin?: ValueOrigin | null;
  country_origin?: ValueOrigin | null;
  sector_origin?: ValueOrigin | null;
}

export type ValueOrigin = "analyst" | "organization" | "computed";

export interface AlertCorrectionInput {
  severity?: AlertSeverity | null;
  country?: string | null;
  sector?: string | null;
  // Obligatoire (5 caractères au moins) : une correction sans motif n'est
  // pas contestable.
  reason: string;
}


export interface AlertTriageInput {
  assignee?: string | null;
  analyst_note?: string | null;
  resolution_reason?: string | null;
}

export interface AlertListResponse {
  total: number;
  offset: number;
  limit: number;
  items: AlertApi[];
}

export interface AlertListParams {
  status?: AlertStatus;
  entityId?: string;
  // Groupe : ses alertes ET celles de ses filiales.
  groupId?: string;
  // Filtre SERVEUR : le total suit le filtre, contrairement à une sélection
  // faite après coup dans la page (la pagination annoncerait sinon plus
  // d'alertes qu'elle n'en sert).
  severities?: AlertSeverity[];
  // Journée (YYYY-MM-DD) : « ce qui est arrivé aujourd'hui ».
  alertDate?: string;
  offset?: number;
  limit?: number;
}

export interface DigestParams {
  severities?: AlertSeverity[];
  alertDate?: string;
  status?: AlertStatus;
  groupId?: string;
}

export interface DigestResponse {
  alert_count: number;
  model: string;
  digest: string;
  // Périmètre réellement résumé, en clair. À afficher avec le texte : un
  // résumé dont on ignore l'assiette n'est pas vérifiable.
  scope: string;
}

export interface AlertDatesResponse {
  dates: string[];
}

export interface DeleteAllAlertsResponse {
  deleted_count: number;
}

function buildQuery(params: AlertListParams): string {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.entityId) search.set("entity_id", params.entityId);
  if (params.groupId) search.set("group_id", params.groupId);
  // Paramètre répétable : ?severity=high&severity=medium
  for (const s of params.severities ?? []) search.append("severity", s);
  if (params.alertDate) search.set("alert_date", params.alertDate);
  search.set("offset", String(params.offset ?? 0));
  search.set("limit", String(params.limit ?? 50));
  return search.toString();
}

function buildDigestQuery(params: DigestParams): string {
  const search = new URLSearchParams();
  for (const s of params.severities ?? []) search.append("severity", s);
  if (params.alertDate) search.set("alert_date", params.alertDate);
  if (params.status) search.set("status", params.status);
  if (params.groupId) search.set("group_id", params.groupId);
  return search.toString();
}

export const alertsApi = {
  triage: (id: string, payload: AlertTriageInput) =>
    api.patch<AlertApi>(`/api/alerts/${id}/triage`, payload),
  list: (params: AlertListParams = {}) =>
    api.get<AlertListResponse>(`/api/alerts?${buildQuery(params)}`),
  get: (id: string) => api.get<AlertApi>(`/api/alerts/${id}`),
  updateStatus: (id: string, status: AlertStatus) =>
    api.patch<AlertApi>(`/api/alerts/${id}/status`, { status }),
  generate: () =>
    api.post<{ created_or_updated: AlertApi[] }>("/api/alerts/generate"),
  summarize: (id: string) => api.post<AlertApi>(`/api/alerts/${id}/summarize`),
  deleteAll: () => api.delete<DeleteAllAlertsResponse>("/api/alerts"),
  documents: (id: string) =>
    api.get<AlertEvidenceResponse>(`/api/alerts/${id}/documents`),
  modusOperandi: (id: string) =>
    api.get<AlertModusOperandiResponse>(`/api/alerts/${id}/modus-operandi`),
  dates: () => api.get<AlertDatesResponse>("/api/alerts/dates"),
  digest: (params: DigestParams = {}) =>
    api.post<DigestResponse>(`/api/alerts/digest?${buildDigestQuery(params)}`),
  correct: (id: string, payload: AlertCorrectionInput) =>
    api.put<AlertApi>(`/api/alerts/${id}/correction`, payload),
  cancelCorrection: (id: string) =>
    api.delete<AlertApi>(`/api/alerts/${id}/correction`),
  remind: (id: string) => api.post<AlertApi>(`/api/alerts/${id}/remind`, {}),
  // Le rapport est un FICHIER : il se transmet, il s'archive.
  //
  // ⚠️ Passe par `downloadFile` et NON par un `<a href>`. Deux raisons, toutes
  // deux constatées : un chemin relatif fait naviguer le navigateur vers le
  // serveur de l'interface (qui a répondu « page introuvable »), et un lien
  // ordinaire ne porte pas l'en-tête `Authorization` — il recevrait un 401.
  downloadReport: (id: string) =>
    downloadFile(`/api/alerts/${id}/report.pdf`, `rapport-alerte-${id}.pdf`),
  // Nom de repli seulement : le serveur fournit le vrai (stix-<sujet>-<date>).
  downloadStix: (id: string) =>
    downloadFile(`/api/alerts/${id}/stix.json`, `stix-alerte-${id}.json`),
};


// Miroir de AlertEvidenceResponse (backend/app/api/routers/alerts.py).
export interface AlertDetectionApi {
  id: string;
  type: string;
  value_masked: string;
  severity: string | null;
  validated: boolean;
  corroborated_group: string | null;
  corroboration_status: string | null;
  corroborated_groups: string[] | null;
  corroboration_match: "domain" | "name" | null;
}

export interface AlertEvidenceDocumentApi {
  document_id: string;
  title: string | null;
  // Souvent un `.onion` : consultable seulement via Tor. À distinguer de la
  // preuve clearnet portée par l'alerte (`corroboration_evidence_url`).
  url: string;
  source_name: string | null;
  collector: string;
  published_at: string | null;
  fetched_at: string;
  content_preview: string;
  detections: AlertDetectionApi[];
}

export interface AlertEvidenceResponse {
  alert_id: string;
  // Nombre RÉEL de documents de l'alerte : peut dépasser la liste renvoyée si
  // le plafond serveur tronque.
  document_count: number;
  documents: AlertEvidenceDocumentApi[];
}

// ---- Mode opératoire des gangs (source tierce : ransomware.live) ----------
// ⚠️ Documenté SUR LE GANG, à partir d'autres incidents : jamais le vecteur de
// CETTE compromission. Le serveur fournit la mise en garde (`caveat`) pour que
// la formulation soit la même partout.

export type GangProfileStatus = "documented" | "undocumented" | "unavailable";

export interface GangTechniqueApi {
  tactic_id: string;
  tactic_name: string;
  technique_id: string;
  technique_name: string;
  details: string | null;
  // null si l'identifiant n'a pas la forme attendue (il vient d'un tiers).
  url: string | null;
}

export interface GangModusOperandiApi {
  gang: string;
  status: GangProfileStatus;
  victims: string[];
  techniques: GangTechniqueApi[];
  // Outils publiés par la source, regroupés par catégorie ("" = sans catégorie).
  tool_groups: { category: string; tools: string[] }[];
  cves: { cve: string; url: string | null }[];
}

export interface AlertModusOperandiResponse {
  alert_id: string;
  caveat: string;
  gangs: GangModusOperandiApi[];
}
