import type { AlertApi } from "../api/alerts";
import type { EntityApi } from "../api/entities";
import type { AlertSeverity } from "../types/domain";
import { jour } from "./format";

/** Rang de tri : la gravite d'abord, la fraicheur ensuite.
 *
 * ⚠️ Trier par date reléguait l'unique alerte critique au milieu de la liste :
 * l'echelle calculee cote serveur devenait invisible a l'ecran.
 */
export const RANG_SEVERITE: Record<AlertSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

/** Comparateur unique, partage par le poste de veille et la page Alertes.
 * Deux definitions du meme tri finissent par diverger. */
export function parGraviteEtFraicheur(a: AlertApi, b: AlertApi): number {
  const gravite = (RANG_SEVERITE[a.severity] ?? 9) - (RANG_SEVERITE[b.severity] ?? 9);
  if (gravite !== 0) return gravite;
  return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
}

/** Ce sur quoi porte l'alerte.
 *
 * Une alerte de perimetre geographique n'a aucune entite : afficher un
 * identifiant vide laisserait croire a une donnee manquante, alors que c'est
 * justement son interet — elle signale une victime que personne n'avait
 * declaree.
 */
export function sujetAlerte(alerte: AlertApi, entitesParId: Record<string, EntityApi>): string {
  if (alerte.entity_id) return entitesParId[alerte.entity_id]?.name ?? alerte.entity_id;
  // Le serveur nomme la victime d'une alerte régionale ; sans lui, quatre
  // alertes portaient le même titre « Afrique — victime non déclarée ».
  if (alerte.subject_label) return alerte.subject_label;
  if (alerte.region) return `${alerte.region} — victime non déclarée`;
  return "Périmètre non précisé";
}

/** Domaine surveille de l'entite, quand elle en declare un.
 *
 * ⚠️ Rend `null` plutot qu'une chaine vide : une entite peut n'avoir que des
 * selecteurs `keyword`, et une alerte regionale n'a pas d'entite du tout. Le
 * composant appelant doit alors n'afficher AUCUNE ligne, pas un tiret qui
 * ressemblerait a une donnee perdue.
 */
export function domaineAlerte(
  alerte: AlertApi,
  entitesParId: Record<string, EntityApi>,
): string | null {
  if (!alerte.entity_id) return null;
  const entite = entitesParId[alerte.entity_id];
  const domaine = entite?.selectors.find((s) => s.type === "domain");
  return domaine?.value ?? null;
}

/** Phrase de corroboration — JAMAIS le statut technique.
 *
 * ⚠️ Mesure du 2026-09-02 : le mot « exclusive » se lit spontanement comme
 * « exclusif, donc remarquable », et le modele comme le lecteur en tirent
 * l'inverse de la verite. Trois etats a ne jamais fondre en un booleen :
 * confirmee par un tiers · vue par nous seuls (ce n'est PAS un doute) ·
 * jamais confrontee (une ABSENCE DE MESURE, pas un resultat negatif).
 */
export function libelleCorroboration(alerte: AlertApi): {
  texte: string;
  ton: "ok" | "neutre";
} {
  if (alerte.corroboration_status === "corroborated") {
    const gang = alerte.corroborated_group;
    // Une double revendication se signale, elle ne se tait pas.
    const autres = (alerte.corroborated_groups ?? []).filter((g) => g !== gang).length;
    const base = gang ? `confirmée · ${gang}` : "confirmée par un tiers";
    return { texte: autres ? `${base} +${autres}` : base, ton: "ok" };
  }
  if (alerte.corroboration_status === "exclusive") {
    return { texte: "vue par nous seuls", ton: "neutre" };
  }
  if (alerte.corroboration_status === "not_applicable") {
    // Mentions de forum ou infrastructure : pas une revendication, rien à
    // confronter. À ne pas confondre avec « jamais confrontée ».
    return { texte: "sans objet", ton: "neutre" };
  }
  return { texte: "jamais confrontée", ton: "neutre" };
}

/** Reference courte et lisible d'une alerte.
 *
 * ⚠️ La maquette proposait un numero de dossier (« ALR-2026-0914 ») que la
 * base ne produit pas : les alertes sont identifiees par UUID. Inventer un
 * compteur cote interface donnerait une reference que le backend ne connait
 * pas et qu'aucun export ne retrouverait. On affiche donc le vrai
 * identifiant, tronque pour rester lisible.
 */
export function referenceCourte(alerte: AlertApi): string {
  return alerte.id.slice(0, 8);
}

export { ageRelatif } from "./format";

/** Nom du pays en français depuis son code ISO (« NA » → « Namibie »).
 *
 * Généré par le navigateur (`Intl.DisplayNames`), jamais tapé de mémoire :
 * un nom de pays erroné serait une erreur invisible. Code illisible → le code
 * tel quel, plutôt que rien.
 */
export function nomPays(code: string | null | undefined): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames(["fr"], { type: "region" }).of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/** Ligne de faits d'une alerte pour la liste : groupe, secteur, pays, date.
 *
 * ⚠️ Remplace le début du résumé IA dans la liste : celui-ci commençait
 * presque toujours par « Une alerte de sécurité critique signale… », qui
 * répète la gravité affichée à côté. Ces faits sont produits par le code ;
 * le résumé reste dans le dossier (et en infobulle).
 */
export function faitsAlerte(alerte: AlertApi): string[] {
  const faits: string[] = [];
  const gangs = alerte.corroborated_groups ?? (alerte.corroborated_group ? [alerte.corroborated_group] : []);
  if (gangs.length) faits.push(`revendiquée par ${gangs.join(", ")}`);
  if (alerte.victim_sector_label) faits.push(alerte.victim_sector_label);
  const pays = nomPays(alerte.victim_country);
  if (pays) faits.push(pays);
  if (alerte.victim_attack_date) {
    faits.push(`attaque du ${jour(alerte.victim_attack_date)}`);
  }
  return faits;
}
