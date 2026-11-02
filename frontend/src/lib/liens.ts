/** Adresse sûre pour un `href`, ou `undefined` (audit du 2026-10-06).
 *
 * ⚠️ Les URL affichées viennent en grande partie de pages publiées par des
 * ATTAQUANTS (sites de fuite, forums) ou de services tiers. Un lien
 * `javascript:…` s'exécuterait au clic dans la page de l'analyste, avec accès
 * aux jetons de session. Seuls `http:` et `https:` deviennent cliquables ; le
 * reste s'affiche comme du texte. Mesuré à l'audit : 0 URL dangereuse en base
 * — c'est une défense en profondeur, pas un correctif après coup. */
export function hrefSur(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const protocole = new URL(url).protocol;
    return protocole === "http:" || protocole === "https:" ? url : undefined;
  } catch {
    return undefined;
  }
}
