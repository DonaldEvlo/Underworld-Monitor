// Miroir TypeScript des contrats Pydantic (backend/app/contracts/). Garder en
// phase avec les enums backend — ce sont les mêmes valeurs, pas une réinterprétation.

export type SourceType = "onion" | "paste" | "telegram" | "forum";

// Miroir de DetectionType (backend/app/contracts/detection.py).
//
// ⚠️ Quatre types manquaient ici alors qu'ils existent en base et comptent
// parmi les plus nombreux (`organization` : 9 996 détections). Leur absence ne
// provoquait aucune erreur — elle affichait simplement le nom technique brut
// (« Source_topic », « Distribution_channel ») dans l'interface.
export type DetectionType =
  | "email"
  | "iban"
  | "card"
  | "credentials"
  | "api_key"
  | "crypto_wallet"
  | "phone"
  | "domain"
  | "volume"
  | "organization"
  | "source_topic"
  | "announcement"
  | "distribution_channel";

export type AlertSeverity = "low" | "medium" | "high" | "critical";

export type AlertStatus = "open" | "acknowledged" | "resolved";

export interface Source {
  id: string;
  name: string;
  type: SourceType;
  url: string;
  active: boolean;
  lastCollectedAt: string | null;
  itemsLast24h: number;
  volumeLast24h: string;
  status: "online" | "polling" | "degraded" | "offline";
}

export interface Detection {
  id: string;
  documentId: string;
  type: DetectionType;
  valueMasked: string;
  confidence: number;
  sourceName: string;
  detectedAt: string;
}

export interface Alert {
  id: string;
  title: string;
  summary: string;
  severity: AlertSeverity;
  status: AlertStatus;
  createdAt: string;
}
