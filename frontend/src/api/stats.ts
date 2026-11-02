import type { AlertSeverity } from "../types/domain";
import { api } from "./client";

export interface RecentDetectionApi {
  id: string;
  type: string;
  value_masked: string;
  severity: AlertSeverity;
  created_at: string;
}

export interface EntitySummaryApi {
  entity_id: string;
  entity_name: string;
  total_detections: number;
  counts_by_type: Record<string, number>;
  counts_by_severity: Partial<Record<AlertSeverity, number>>;
  recent_detections: RecentDetectionApi[];
}

export interface EntitiesStatsResponse {
  entities: EntitySummaryApi[];
}

export interface CountryStatApi {
  country_code: string;
  continent: string;
  victim_domains: number;
}

export interface ContinentStatApi {
  continent: string;
  victim_domains: number;
}

/** Un groupe attaquant : combien de victimes, et où il frappe. */
export interface GroupStatApi {
  source_id: string;
  // Nom nettoyé du gang — les suffixes techniques du nom de source
  // (« (DLS) », « (New Dark mirror 1) ») ne disent rien à un analyste.
  name: string;
  source_name: string;
  gang_slug?: string | null;
  active: boolean;
  victim_domains: number;
  located_victim_domains: number;
  countries: CountryStatApi[];
  continents: ContinentStatApi[];
  // `null` = ce site ne date pas ses annonces, PAS « inactif ».
  last_published_at: string | null;
  last_collected_at: string | null;
  corroborated_domains: number;
}

export interface GroupsResponse {
  groups: GroupStatApi[];
  undetermined_victim_domains: number;
}

export interface GeographyResponse {
  total_victim_domains: number;
  located_victim_domains: number;
  // gTLD (.com/.net/.org) : aucun indice de pays. Ce n'est PAS un pays
  // « inconnu » et cela ne doit jamais apparaitre comme une zone sur la carte.
  undetermined_victim_domains: number;
  countries: CountryStatApi[];
  continents: ContinentStatApi[];
}

export const statsApi = {
  governance: (month?: string) =>
    api.get<GovernanceResponse>(
      `/api/stats/governance${month ? `?month=${encodeURIComponent(month)}` : ""}`,
    ),
  entities: () => api.get<EntitiesStatsResponse>("/api/stats/entities"),
  geography: () => api.get<GeographyResponse>("/api/stats/geography"),
  groups: () => api.get<GroupsResponse>("/api/stats/groups"),
  threatActors: (params: { continent?: string; country?: string; months?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.continent) q.set("continent", params.continent);
    if (params.country) q.set("country", params.country);
    if (params.months) q.set("months", String(params.months));
    return api.get<ThreatActorsResponse>(`/api/stats/threat-actors?${q.toString()}`);
  },
};

// ---- Qui attaque quelle région (pipeline/reporting/threat_actors.py) -------
// Historiques ransomware.live en cache : COMPTES seulement, aucune victime
// nommée. `coverage_gangs` doit être affiché avec le classement.

export interface ThreatActorCountry {
  code: string;
  count: number;
}

export interface ThreatActor {
  gang: string;
  victims: number;
  share: number | null;
  countries: ThreatActorCountry[];
  country_count: number;
  critical_sector_share: number;
  last_discovered: string;
  // Nous lisons le site de ce groupe (source active).
  collected: boolean;
}

export interface ThreatActorsResponse {
  window_start: string;
  months: number;
  continent: string | null;
  country: string | null;
  total: number;
  gangs: number;
  unknown_country: number;
  collected_victims: number;
  collected_share: number | null;
  critical_sector_share: number | null;
  actors: ThreatActor[];
  other_actors: number;
  countries: ThreatActorCountry[];
  continents: { label: string; count: number }[];
  coverage_gangs: number;
  highlighted: string[];
  computed_at: string;
}

// ---- Gouvernance (RSSI) : AGRÉGATS UNIQUEMENT ------------------------------
// Miroir de pipeline/reporting/governance.py. Aucun nom de victime, aucune
// valeur : le profil RSSI ne voit pas le détail des contenus.

export interface GovernanceRank {
  label: string;
  count: number;
}

export interface GovernanceSector extends GovernanceRank {
  label_fr: string;
  // Secteur critique au sens de NIS2 (annexe I).
  critical: boolean;
}

export interface GovernanceWeek {
  week: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface GovernanceServiceActivity {
  total: number;
  first_alert_date: string | null;
  last_alert_date: string | null;
  by_severity: Record<"critical" | "high" | "medium" | "low", number>;
  by_status: Record<string, number>;
  weekly: GovernanceWeek[];
  by_sector: GovernanceSector[];
  by_country: GovernanceRank[];
  by_gang: GovernanceRank[];
  by_credibility: Record<string, number>;
  // null = AUCUN cas mesuré (jamais 0, qui dirait « traité instantanément »).
  median_hours_to_acknowledge: number | null;
  median_hours_to_resolve: number | null;
  treated: number;
  false_positive_rate: number | null;
}

export interface GovernanceSectorThreat {
  continents: string[];
  window_start: string;
  total: number;
  critical_sector_share: number | null;
  monthly: { month: string; critical_sector: number; other: number }[];
  by_sector: GovernanceSector[];
  by_country: GovernanceRank[];
  by_gang: GovernanceRank[];
  // Nombre de gangs présents dans le cache au moment du calcul.
  coverage_gangs: number;
}

export interface GovernanceContinent {
  label: string;
  count: number;
  share: number | null;
  critical_sector_share: number;
  // Continent surveillé : mis en avant, jamais isolé du reste du monde.
  highlighted: boolean;
}

export interface GovernanceWorldThreat {
  window_start: string;
  total: number;
  critical_sector_share: number | null;
  highlighted: string[];
  by_continent: GovernanceContinent[];
  coverage_gangs: number;
}

export interface GovernanceResponse {
  computed_at: string;
  month: string | null;
  // Début du CORPUS (toutes alertes), indépendant du mois affiché.
  corpus_first_alert_date: string | null;
  service: GovernanceServiceActivity;
  sector_threat: GovernanceSectorThreat;
  world_threat: GovernanceWorldThreat;
}
