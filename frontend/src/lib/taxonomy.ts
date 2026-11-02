import type { AlertSeverity, AlertStatus, DetectionType, SourceType } from "../types/domain";

export const detectionTypeLabels: Record<DetectionType, string> = {
  email: "Email",
  iban: "IBAN",
  card: "Carte bancaire",
  credentials: "Identifiants",
  api_key: "Clé API",
  crypto_wallet: "Wallet crypto",
  phone: "Téléphone",
  domain: "Domaine",
  volume: "Volume",
  organization: "Organisation",
  source_topic: "Rubrique de source",
  announcement: "Annonce",
  distribution_channel: "Canal de diffusion",
};

// Nom technique du collecteur (voir Collector.COLLECTOR_NAME cote backend,
// pipeline/collect/*/adapter.py) -> libelle lisible pour la page Collecte.
// Cle absente = collecteur generique (CyberScraper), pas d'entree dediee.
export const collectorLabels: Record<string, string> = {
  akira: "Akira (ransomware leak site)",
  xssf: "XSSF (actualités)",
  xenforo_latest: "XenForo (derniers messages)",
  breachforums_guest: "BreachForums (accès invité)",
  mybb_latest: "MyBB (DarkForums / Spear)",
  exilio404: "Exilio404 (Doxxing)",
  doxbyte: "DoxByte (pastes)",
  cyberscraper: "CyberScraper (générique)",
  ransomlook: "RansomLook (annonces de victimes)",
};

export const sourceTypeLabels: Record<SourceType, string> = {
  onion: "Tor (.onion)",
  paste: "Paste site",
  telegram: "Telegram",
  forum: "Forum",
};

export const sourceTypeIcons: Record<SourceType, string> = {
  onion: "security",
  paste: "content_paste",
  telegram: "send",
  forum: "forum",
};

export const severityLabels: Record<AlertSeverity, string> = {
  low: "Faible",
  medium: "Moyenne",
  high: "Élevée",
  critical: "Critique",
};

export const severityColors: Record<AlertSeverity, string> = {
  low: "text-ink-dim border-line bg-panel-raised",
  medium: "text-info border-info/30 bg-info-dim/40",
  high: "text-warn border-warn/40 bg-warn-dim/40",
  critical: "text-critical border-critical/50 bg-critical-dim/50",
};

// ⚠️ UNE seule définition des couleurs de gravité. Elles étaient recopiées
// dans 5 fichiers (liste, dossier, investigation, statistiques, poste de
// veille) : deux copies du même fait finissent par diverger.
/** Fond plein : liseré de ligne, pastille, segment de barre. */
export const severityFond: Record<AlertSeverity, string> = {
  critical: "bg-critical",
  high: "bg-warn",
  medium: "bg-info",
  low: "bg-ink-faint",
};
/** Texte seul. */
export const severityTexte: Record<AlertSeverity, string> = {
  critical: "text-critical",
  high: "text-warn",
  medium: "text-info",
  low: "text-ink-faint",
};
/** Bordure d'un cadre (en-tête de dossier, d'investigation). */
export const severityCadre: Record<AlertSeverity, string> = {
  critical: "border-critical/35",
  high: "border-warn/35",
  medium: "border-info/30",
  low: "border-line",
};
/** Pastille de filtre (bordure + fond léger + texte). */
export const severityPuce: Record<AlertSeverity, string> = {
  critical: "border-critical/40 bg-critical/[0.14] text-critical",
  high: "border-warn/30 bg-warn/[0.12] text-warn",
  medium: "border-line bg-panel text-info",
  low: "border-line bg-panel text-ink-faint",
};

export const statusLabels: Record<AlertStatus, string> = {
  open: "Ouverte",
  acknowledged: "Acquittée",
  resolved: "Résolue",
};

// --- Crédibilité (migration 0031) --------------------------------------
// « La fuite est-elle réelle ? », axe DISTINCT de la gravité. `published`
// reste une DÉCLARATION du groupe (« les données sont en ligne »), jamais une
// vérification de notre part : le projet ne télécharge pas le contenu des
// fuites.
export type CredibilityLevel =
  | "confirmed"
  | "doubtful"
  | "published"
  | "claimed"
  | "not_evaluated";

export const credibilityLabels: Record<CredibilityLevel, string> = {
  confirmed: "Confirmée",
  doubtful: "Douteuse",
  published: "Publiée par le groupe",
  claimed: "Revendiquée seulement",
  not_evaluated: "Non évaluée",
};

// ⚠️ Les couleurs rouge et orange appartiennent à la GRAVITÉ (critique,
// élevée). Les réutiliser ici faisait lire « revendiquée seulement » comme une
// gravité élevée, et « douteuse » comme critique : deux axes distincts
// confondus à l'œil. Seule « confirmée » garde une couleur, le vert, qui
// n'est pas une couleur de gravité ; le libellé porte le reste.
export const credibilityTone: Record<CredibilityLevel, "ok" | "critique" | "warn" | "neutre"> = {
  confirmed: "ok",
  doubtful: "neutre",
  published: "neutre",
  claimed: "neutre",
  not_evaluated: "neutre",
};

export function credibilityLabel(level: string | null): string | null {
  return level && level in credibilityLabels
    ? credibilityLabels[level as CredibilityLevel]
    : null;
}

/** Notation Admiralty — libellés du code OTAN (miroir de
 * backend/app/pipeline/alerting/admiralty.py). */
export const admiraltySourceLabels: Record<string, string> = {
  A: "complètement fiable",
  B: "habituellement fiable",
  C: "assez fiable",
  D: "pas toujours fiable",
  E: "non fiable",
  F: "fiabilité non évaluable",
};

export const admiraltyInfoLabels: Record<string, string> = {
  "1": "confirmée par d'autres sources",
  "2": "probablement vraie",
  "3": "possiblement vraie",
  "4": "douteuse",
  "5": "improbable",
  "6": "véracité non évaluable",
};

/** Consigne de diffusion du rapport (FIRST TLP 2.0) — miroir de
 * `TLP_RAPPORT` côté serveur. */
export const TLP_RAPPORT = "TLP:AMBER+STRICT";
