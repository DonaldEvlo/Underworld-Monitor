import type { SourceTestEntry, SourceTestJob } from "../api/sources";
import { ageRelatif } from "./alertes";

/**
 * ⚠️ Un « injoignable » sur une source qui exige un navigateur ne prouve RIEN.
 * Le test envoie une requête HTTP simple ; Dread, par exemple, la met en file
 * d'attente anti-DDoS ou la laisse expirer, alors que son collecteur (vrai
 * navigateur) ramène ses fils le même jour. Constaté le 2026-09-11 : Dread
 * paraissait en panne dans le test avec 85 documents collectés le jour même.
 * Ces cas sont donc comptés À PART, jamais parmi les injoignables.
 */
export function estNonConcluant(entree: SourceTestEntry): boolean {
  return entree.state === "unreachable" && entree.requires_js;
}

/** Libellé et couleurs d'une source pendant ou après un test. */
export function etatTestAffiche(entree: SourceTestEntry): {
  texte: string;
  ton: string;
  point: string;
  anime: boolean;
} {
  switch (entree.state) {
    case "pending":
      return { texte: "en attente de test", ton: "text-ink-faint", point: "bg-ink-faint", anime: false };
    case "retrying":
      return { texte: "nouvel essai, circuit renouvelé…", ton: "text-warn", point: "bg-warn", anime: true };
    case "reachable":
      return {
        texte: `joignable${entree.http_status !== null ? ` · HTTP ${entree.http_status}` : ""}`,
        ton: "text-ok",
        point: "bg-ok",
        anime: false,
      };
    case "unreachable":
      return entree.requires_js
        ? { texte: "non concluant (navigateur requis)", ton: "text-info", point: "bg-info", anime: false }
        : { texte: "injoignable", ton: "text-critical", point: "bg-critical", anime: false };
    case "untested":
      return { texte: "non testée", ton: "text-ink-faint", point: "bg-ink-faint", anime: false };
  }
}

/** Preuve de fonctionnement indépendante du test : la dernière collecte
 * RÉUSSIE (`last_collected_at` n'est jamais écrit sur un échec). */
export function preuveCollecte(entree: SourceTestEntry): string {
  return entree.last_collected_at
    ? `collectée avec succès ${ageRelatif(entree.last_collected_at)}`
    : "jamais collectée avec succès";
}

/** Ce qui demande l'attention en premier : les vrais échecs, puis ce qui
 * tourne ; les non concluants ne passent pas devant une vraie panne. */
export function rangAffichage(entree: SourceTestEntry): number {
  if (estNonConcluant(entree)) return 3;
  return { unreachable: 0, retrying: 1, pending: 2, untested: 4, reachable: 5 }[entree.state];
}

export function libellePortee(job: SourceTestJob): string {
  if (job.scope === "one") return job.entries[0] ? `une source : ${job.entries[0].name}` : "une source";
  return job.scope === "active" ? "sources actives" : "toutes les sources, inactives comprises";
}

/** « 1 min 20 », « 45 s ». */
export function dureeDepuis(debutIso: string, finIso?: string | null): string {
  const fin = finIso ? new Date(finIso).getTime() : Date.now();
  const secondes = Math.max(0, Math.round((fin - new Date(debutIso).getTime()) / 1000));
  if (secondes < 60) return `${secondes} s`;
  return `${Math.floor(secondes / 60)} min ${String(secondes % 60).padStart(2, "0")}`;
}
