/** Rôles, côté interface — miroir de `backend/app/core/roles.py`.
 *
 * ⚠️ AUCUNE SÉCURITÉ ICI. La garde qui compte est serveur : elle répond 403 et
 * ne dépend pas du navigateur. Ce module sert à ne pas AFFICHER ce que le
 * serveur refusera — une interface qui promet exactement ce qu'elle refuse est
 * pire qu'une interface qui n'affiche rien (même leçon que la barre de
 * recherche désactivée mais visible sur trois pages, corrigée le 2026-09-04).
 *
 * ⚠️ CE MODULE EST L'AUTORITÉ UNIQUE DU PÉRIMÈTRE D'UNE PAGE. Le périmètre a
 * d'abord vécu dans le menu (`Sidebar.tsx`) : les routes, elles, n'étaient pas
 * gardées du tout, si bien qu'un rôle qui tapait l'URL à la main ouvrait une
 * page dont chaque appel répondait 403. Deux définitions du même fait
 * divergent toujours — c'était déjà arrivé aux domaines d'infrastructure,
 * écrits à trois endroits avec des variantes.
 */

export type Role = "analyst" | "admin" | "viewer";

/** Ce à quoi une page donne accès. Volontairement calqué sur les ensembles du
 * backend, pour qu'une divergence se voie. */
export type Perimetre = "alertes" | "corpus" | "administration" | "agrege";

const ACCES: Record<Perimetre, readonly Role[]> = {
  // Le RSSI ne consulte pas le détail des contenus — décision de conception,
  // pas oubli (voir core/roles.py).
  alertes: ["analyst", "admin"],
  corpus: ["analyst", "admin"],
  administration: ["admin"],
  agrege: ["analyst", "admin", "viewer"],
};

/** Normalise un rôle venu du serveur.
 *
 * ⚠️ Une valeur inconnue retombe sur le rôle le MOINS puissant, jamais sur
 * `admin` — même doctrine que `role_de()` côté serveur. */
export function roleDe(role: string | undefined): Role {
  return role === "admin" || role === "analyst" || role === "viewer" ? role : "viewer";
}

/** `true` si ce rôle peut ouvrir ce périmètre. */
export function peutAcceder(role: string | undefined, perimetre: Perimetre): boolean {
  return ACCES[perimetre].includes(roleDe(role));
}

/** `true` si ce rôle peut CONFIGURER : créer, modifier, supprimer, déclencher
 * une collecte, purger.
 *
 * ⚠️ UN SEUL PRÉDICAT, PAS QUATRE. La tentation est d'écrire
 * `peutPurger` / `peutCollecter` / `peutConfigurer` pour que les appels se
 * lisent mieux. Côté serveur, ces trois gestes tombent tous dans le MÊME
 * ensemble `PEUT_ADMINISTRER` : inventer ici une granularité que le serveur
 * n'a pas fabriquerait une divergence, et laisserait croire qu'un rôle peut
 * l'un sans l'autre. Le jour où le serveur sépare ces droits, ce module les
 * sépare aussi — pas avant. */
export function peutAdministrer(role: string | undefined): boolean {
  return roleDe(role) === "admin";
}

export function libelleRole(role: string | undefined): string {
  if (role === "admin") return "Administrateur";
  if (role === "analyst") return "Analyste";
  if (role === "viewer") return "Direction";
  return "—";
}

/** Périmètre exigé par chaque route, dans l'ordre de spécificité décroissante.
 *
 * ⚠️ LE PÉRIMÈTRE D'UNE PAGE EST CELUI DE SA LECTURE, jamais celui de son
 * geste le plus puissant. `/sources` et `/planification` sont lisibles par
 * l'analyste côté serveur (routeurs en `PEUT_VOIR_LE_CORPUS`, écritures en
 * `PEUT_ADMINISTRER`) : les classer « administration » lui masquait des pages
 * auxquelles il a droit. Pour la planification c'est une décision écrite —
 * « la fraîcheur de ses alertes dépend de la date de la dernière collecte, il
 * doit pouvoir la LIRE sans pouvoir la MODIFIER ». Ce sont les CONTRÔLES de
 * ces pages qui sont réservés à l'administrateur (`peutAdministrer`), pas les
 * pages elles-mêmes.
 */
const PERIMETRE_PAR_ROUTE: readonly (readonly [string, Perimetre])[] = [
  // Poste de veille : écran de l'ANALYSTE malgré son air de tableau de bord —
  // il interroge alertes, documents, détections, entités et sources.
  ["/alerts", "alertes"],
  ["/documents", "corpus"],
  ["/detections", "corpus"],
  ["/entities", "corpus"],
  ["/watchlist", "corpus"],
  ["/lookup", "corpus"],
  ["/fiabilite", "corpus"],
  // Lisibles par l'analyste, modifiables par l'administrateur seul.
  ["/sources", "corpus"],
  ["/planification", "corpus"],
  // Entièrement administration : tous leurs appels sont en PEUT_ADMINISTRER.
  ["/collecte", "administration"],
  ["/recherche", "administration"],
  ["/settings", "administration"],
  ["/comptes", "administration"],
  ["/telegram", "administration"],
  // Vues agrégées : le seul périmètre ouvert à la direction.
  ["/gouvernance", "agrege"],
  ["/perimetre", "agrege"],
  ["/cartographie", "agrege"],
  ["/statistics", "agrege"],
  ["/", "alertes"],
];

/** Périmètre d'une adresse, ou `undefined` si elle n'est pas connue.
 *
 * ⚠️ `undefined` signifie « route inconnue », et se traite comme une page
 * introuvable — JAMAIS comme un accès libre. Une route ajoutée sans être
 * déclarée ici ne doit pas s'ouvrir à tout le monde par défaut. */
export function perimetreDeRoute(pathname: string): Perimetre | undefined {
  const chemin = pathname.replace(/\/+$/, "") || "/";
  for (const [prefixe, perimetre] of PERIMETRE_PAR_ROUTE) {
    if (prefixe === "/") {
      if (chemin === "/") return perimetre;
      continue;
    }
    if (chemin === prefixe || chemin.startsWith(`${prefixe}/`)) return perimetre;
  }
  return undefined;
}

/** Page d'accueil d'un rôle.
 *
 * ⚠️ Le RSSI n'atterrit PAS sur le poste de veille : mesuré au navigateur, six
 * de ses sept appels y répondaient 403. Il est envoyé sur la vue de
 * Gouvernance (2026-10-01), faite pour lui : agrégats, tendance, menace
 * sectorielle et rapport mensuel. */
export function routeAccueil(role: string | undefined): string {
  return peutAcceder(role, "alertes") ? "/" : "/gouvernance";
}
