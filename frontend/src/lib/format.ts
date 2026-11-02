/** Formatage des dates : UN seul endroit pour toute l'interface.
 *
 * ⚠️ Avant (2026-10-01) : trois `formatDate`, trois `horodatage`, un `heure`
 * et une cinquantaine d'appels `toLocale…String` dispersés, avec ou sans
 * secondes, avec ou sans année. Un même écran affichait « 2026-09-24 » et
 * « 24/09/2026 ». Le lecteur doit reconnaître une date sans la déchiffrer.
 *
 * Une date absente ou illisible rend le texte de repli, jamais « Invalid
 * Date » : une absence de date est une information, pas une panne.
 */

const LOCALE = "fr-FR";

function lire(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** « 24/09/2026 22:07 » — l'horodatage de référence. */
export function dateHeure(iso: string | null | undefined, repli = "—"): string {
  const date = lire(iso);
  return date ? date.toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" }) : repli;
}

/** « 24/09 22:07 » — horodatage compact, pour une ligne d'état ou une liste. */
export function dateHeureCourte(iso: string | null | undefined, repli = "—"): string {
  const date = lire(iso);
  return date
    ? date.toLocaleString(LOCALE, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : repli;
}

/** « 24/09/2026 » — le jour seul. */
export function jour(iso: string | null | undefined, repli = "—"): string {
  const date = lire(iso);
  return date ? date.toLocaleDateString(LOCALE) : repli;
}

/** « 22:07 » — l'heure seule. */
export function heure(iso: string | null | undefined, repli = "—"): string {
  const date = lire(iso);
  return date ? date.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" }) : repli;
}

/** Âge relatif (« il y a 11 h »). La date exacte va en infobulle chez
 * l'appelant (`dateHeure`).
 *
 * Une colonne de douze `03/09/2026 20:07:18` quasi identiques est le bruit
 * visuel maximal pour l'information la plus faible.
 */
export function ageRelatif(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const heures = Math.round(minutes / 60);
  if (heures < 24) return `il y a ${heures} h`;
  const jours = Math.round(heures / 24);
  return `il y a ${jours} j`;
}
