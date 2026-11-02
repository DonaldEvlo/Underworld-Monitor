// Préchargement de la Cartographie.
//
// ⚠️ Le globe arrivait EN CASCADE : morceau de la page, puis réponse de
// l'API, puis seulement le téléchargement du moteur 3D (~2 Mo), puis la
// construction des géométries. Mesuré : ~5 s entre le clic et le globe. Les
// deux téléchargements ne dépendent pas l'un de l'autre — ils partent
// désormais ensemble, et dès le survol du lien dans le menu.
//
// Les promesses sont mémorisées : un second appel ne relance rien. Un échec
// (réseau coupé) les oublie, sinon la page resterait bloquée sur une erreur
// jusqu'au rechargement complet de l'application.

type ModuleGlobe = typeof import("../components/cartographie/GlobeVictimes");
type ModulePage = typeof import("../pages/Cartographie");

let globe: Promise<ModuleGlobe> | null = null;
let page: Promise<ModulePage> | null = null;

export function chargerGlobe(): Promise<ModuleGlobe> {
  globe ??= import("../components/cartographie/GlobeVictimes").catch((err: unknown) => {
    globe = null;
    throw err;
  });
  return globe;
}

export function chargerPageCartographie(): Promise<ModulePage> {
  page ??= import("../pages/Cartographie").catch((err: unknown) => {
    page = null;
    throw err;
  });
  return page;
}

/** Au survol du lien : l'analyste a une chance sur deux de cliquer. */
export function prechargerCartographie(): void {
  chargerPageCartographie().catch(() => undefined);
  chargerGlobe().catch(() => undefined);
}
