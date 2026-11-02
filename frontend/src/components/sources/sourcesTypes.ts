import type { SourceType } from "../../types/domain";

/** Types de source proposés dans les formulaires de création et d'édition. */
export const SOURCE_TYPES: SourceType[] = ["onion", "paste", "telegram", "forum"];

/** Préremplissage du formulaire, transmis par la navigation (ex. « ajouter
 * comme source » depuis un lien d'un document). */
export interface SourcePrefill {
  name?: string;
  url?: string;
}
