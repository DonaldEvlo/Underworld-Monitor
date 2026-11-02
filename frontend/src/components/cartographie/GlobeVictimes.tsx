import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import { MeshPhongMaterial } from "three";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import atlas from "world-atlas/countries-110m.json";
import { CONTINENT_COLORS } from "../../data/countryCentroids";
import { Icon } from "../ui/Icon";

// ⚠️ Ce fichier est isolé du reste de la page À DESSEIN : il embarque three.js
// et l'atlas mondial, soit l'essentiel du poids. La page Cartographie le
// charge en différé (`React.lazy`), si bien que les chiffres, la répartition
// par continent et l'avertissement de couverture s'affichent IMMÉDIATEMENT,
// le globe arrivant ensuite. Tout mettre dans un seul module différé faisait
// attendre l'analyste devant une page vide.

export interface CountryFeature {
  id?: string | number;
  properties: { name: string };
  // Necessaire pour mesurer l'etendue d'un pays : c'est elle qui determine la
  // resolution de courbure a lui appliquer (voir `resolutionParPays`).
  geometry?: { coordinates?: unknown };
}

export interface CountryData {
  name: string;
  continent: string;
  count: number;
}

export interface GlobePoint {
  lat: number;
  lng: number;
  code: string;
  name: string;
  continent: string;
  count: number;
  color: string;
}

// ⚠️ Import STATIQUE de l'atlas, et il ne faut pas essayer de le rendre
// asynchrone. Deux tentatives ont échoué en développement, toutes deux
// invisibles au build : `import("...json")` et `import ... from "...json?url"`
// sont servis par Vite avec le type MIME `application/json`, que le navigateur
// REFUSE de charger comme module. La page restait entièrement vide alors que
// `tsc`, `lint` ET `npm run build` passaient tous les trois.
//
// Résolution 110m et non 50m : en 50m, la construction des géométries bloquait
// le fil principal 55 s au total, dont une tâche de 28 s.
const WORLD = feature(
  atlas as unknown as Topology,
  (atlas as unknown as Topology).objects.countries,
) as unknown as { features: CountryFeature[] };

// Sphère opaque : sans elle le globe n'a aucune silhouette et les pays de la
// face arrière transparaissent.
const COULEUR_GLOBE = "#101a26";

// ⚠️ SURFACES DE PAYS OPAQUES — c'est la condition pour que la carte ne fige
// pas l'application (mesuré le 2026-09-11).
//
// `three-globe` crée ses surfaces et ses flancs de pays en matériaux DOUBLE
// FACE. Or three.js dessine un matériau à la fois transparent ET double face
// en DEUX passes (face arrière puis avant), en posant `needsUpdate` à chaque
// passe (`renderObject`, `material.forceSinglePass === false`) : il recalcule
// alors les paramètres de programme de chaque matériau, à CHAQUE image. Avec
// des couleurs rgba, cela faisait 567 matériaux × 2 par image — processeur à
// 100 % en continu (0 ms d'inactivité sur 3 s de profil, en dev comme en
// production), donc toute l'application saccadait tant que la carte était
// ouverte.
//
// Derrière un pays, on ne voit que la sphère : le mélange « couleur × alpha
// sur la sphère » est calculé ici une fois et passé en couleur OPAQUE. Rendu
// identique à l'œil, matériaux non transparents, une seule passe.
// Les contours (lignes simple face) ne sont pas concernés et restent en rgba.
function surGlobe(hex: string, alpha: number): string {
  const lire = (h: string, i: number) => parseInt(h.replace("#", "").slice(i, i + 2), 16);
  const canal = (i: number) =>
    Math.round(lire(COULEUR_GLOBE, i) + (lire(hex, i) - lire(COULEUR_GLOBE, i)) * alpha)
      .toString(16)
      .padStart(2, "0");
  return `#${canal(0)}${canal(2)}${canal(4)}`;
}

// ⚠️ Valeurs relevées après constat : avec un fond transparent, aucune texture
// de globe et des pays à 12 % d'opacité, la carte était techniquement rendue
// (canvas dimensionné, boucle d'animation active, zéro erreur) et pourtant
// INVISIBLE. Un rendu qui fonctionne n'est pas un rendu qu'on voit.
// (Mêmes teintes qu'avant — ardoise à 30 % et 22 % — rendues opaques.)
const COULEUR_SANS_DONNEE = surGlobe("#94a3b8", 0.3);
const COULEUR_FLANC = surGlobe("#94a3b8", 0.22);
const COULEUR_CONTOUR = "rgba(203,213,225,0.85)";

const materiauGlobe = new MeshPhongMaterial({ color: COULEUR_GLOBE });
// ⚠️ Definis HORS du composant : declares dans son corps, ils changeraient
// d'identite a chaque rendu et `react-globe.gl` retessellerait les 241 pays.
const cotePolygone = () => COULEUR_FLANC;
const contourPolygone = () => COULEUR_CONTOUR;

// ⚠️ TROUS NOIRS dans les pays -- signales a l'usage (Antarctique, puis
// Algerie et Mali). Le « cap » d'un polygone est une surface triangulee PUIS
// projetee sur la sphere : entre deux subdivisions, la corde passe SOUS l'arc
// et le fond du globe transparait en sombre.
//
// ⚠️ `capCurvatureResolution` est un PAS EN DEGRES, PAS un nombre de
// subdivisions. Documentation de `three-conic-polygon-geometry` : « The
// resolution in angular degrees of the sphere curvature. The finer the
// resolution, the more the polygon is fragmented ». **Plus petit = plus fin**,
// et le defaut de la bibliotheque est 5.
//
// Le projet etait a **9** -- pose le 2026-09-02 pour la performance, donc deux
// fois plus grossier que le defaut -- et c'est exactement ce qui creusait les
// trous.
//
// ⚠️ Une premiere tentative de correctif a porte les grands pays a 16 puis 24,
// en croyant a un nombre de subdivisions : cela les rendait **encore plus
// grossiers**. L'amelioration alors observee venait entierement du relevement
// d'altitude qui l'accompagnait, pas de la resolution. Mesure comparative :
//   - resolution 24 + altitude 0.004 -> trou reduit, pas supprime ;
//   - resolution 9  + altitude 0.02  -> trous toujours presents ;
//   - **resolution 5, altitude inchangee -> surface pleine.**
// Revenir au defaut suffit donc, sans relever aucune altitude ni traiter les
// grands polygones a part.
const RESOLUTION_COURBURE = 5;

// Hauteur du globe. ⚠️ Fixe et modeste : la colonne laterale est bien plus
// haute que le globe, et une grille CSS etire ses colonnes a la meme hauteur
// par defaut -- le globe se retrouvait perdu au milieu de centaines de pixels
// vides. C'est la boite qui s'aligne sur le globe, pas l'inverse.
const HAUTEUR = 520;

// Bornes de zoom, en altitude de camera (react-globe.gl) : 2.5 est la vue par
// defaut, 0.6 approche jusqu'a lire un pays, 4 recule sur le globe entier.
// 1.9 et non 2.5 (le defaut de la bibliotheque) : a 2.5 la sphere n'occupait
// qu'environ un tiers de la boite, le reste etant du vide sombre.
const ALTITUDE_DEFAUT = 1.9;
const ALTITUDE_MIN = 0.6;
const ALTITUDE_MAX = 4;
const PAS_ZOOM = 1.35;

// Délai sans activité avant de suspendre le rendu. Couvre la plus longue
// transition de caméra (450 ms) et l'inertie de rotation après un lâcher.
const DELAI_REPOS_MS = 2000;

interface Props {
  byAtlasId: Map<string, CountryData>;
  points: GlobePoint[];
  max: number;
}

export default function GlobeVictimes({ byAtlasId, points, max }: Props) {
  const [width, setWidth] = useState(900);
  const containerRef = useRef<HTMLDivElement>(null);
  // Référence au globe pour piloter la caméra depuis les boutons de zoom :
  // `pointOfView` est la seule voie officielle, il n'existe pas de propriété
  // d'altitude déclarative.
  const globeRef = useRef<GlobeMethods | undefined>(undefined);

  // ⚠️ RENDU EN PAUSE AU REPOS. La bibliothèque redessine le globe à chaque
  // image, même quand personne ne le touche : ~866 appels de dessin par image,
  // soit un processeur occupé à ~86 % en continu (mesuré le 2026-09-11), ce
  // qui ralentissait toute l'application tant que la carte était ouverte. Le
  // globe ne bouge que sous la main de l'analyste ou quand les données
  // changent : on reprend alors la boucle, et on la suspend après
  // `DELAI_REPOS_MS` sans activité (l'inertie de rotation s'éteint avant).
  const minuteurRepos = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reveiller = useCallback(() => {
    const globe = globeRef.current;
    if (!globe) return;
    globe.resumeAnimation();
    if (minuteurRepos.current) clearTimeout(minuteurRepos.current);
    minuteurRepos.current = setTimeout(() => globe.pauseAnimation(), DELAI_REPOS_MS);
  }, []);

  useEffect(() => {
    const globe = globeRef.current;
    const element = containerRef.current;
    if (!globe || !element) return;
    const controles = globe.controls();
    controles.addEventListener("change", reveiller);
    const evenements = ["pointermove", "pointerdown", "wheel"] as const;
    for (const e of evenements) element.addEventListener(e, reveiller, { passive: true });
    return () => {
      if (minuteurRepos.current) clearTimeout(minuteurRepos.current);
      controles.removeEventListener("change", reveiller);
      for (const e of evenements) element.removeEventListener(e, reveiller);
    };
  }, [reveiller]);

  // Données ou largeur modifiées (groupe sélectionné, redimensionnement), et
  // premier affichage : le globe doit redessiner, même sans geste.
  useEffect(() => {
    reveiller();
  }, [reveiller, byAtlasId, points, max, width]);

  const zoomer = useCallback((facteur: number) => {
    const globe = globeRef.current;
    if (!globe) return;
    // La transition de caméra avance dans la boucle de rendu : il faut
    // qu'elle tourne.
    reveiller();
    const vue = globe.pointOfView();
    const altitude = Math.min(
      ALTITUDE_MAX,
      Math.max(ALTITUDE_MIN, vue.altitude * facteur),
    );
    // 250 ms : assez pour que l'oeil suive le mouvement, assez court pour que
    // des clics repetes sur « + » restent reactifs.
    globe.pointOfView({ ...vue, altitude }, 250);
  }, [reveiller]);

  // Vue initiale : la bibliotheque place la camera a 2.5, ce qui laisse la
  // sphere petite au milieu d'une large boite. On la rapproche une fois, au
  // montage.
  useEffect(() => {
    globeRef.current?.pointOfView({ lat: 20, lng: 10, altitude: ALTITUDE_DEFAUT });
  }, []);

  const recentrer = useCallback(() => {
    reveiller();
    globeRef.current?.pointOfView(
      { lat: 20, lng: 10, altitude: ALTITUDE_DEFAUT },
      450,
    );
  }, [reveiller]);

  // Le globe est dessiné sur un canvas dimensionné en pixels : il ne se
  // redimensionne pas tout seul comme un bloc CSS.
  //
  // ⚠️ La largeur n'est répercutée que par paliers de 16 px. `ResizeObserver`
  // se déclenche à CHAQUE pixel pendant un redimensionnement ou l'ouverture du
  // tiroir de navigation ; chaque changement d'état relançait un rendu, donc
  // une reconstruction du canvas.
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const mesure = Math.round(entry.contentRect.width / 16) * 16;
      setWidth((precedente) => (precedente === mesure ? precedente : mesure));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // ⚠️ Couleurs et libellés calculés UNE FOIS, pas à chaque appel.
  // `react-globe.gl` reconstruit la géométrie de tous les pays dès qu'un
  // accesseur change d'identité. Des fonctions déclarées dans le corps du
  // composant en changent à chaque rendu — et le `ResizeObserver` en déclenche
  // beaucoup. Les polygones étaient alors retessellés en continu.
  //
  // Teinte du continent, opacité selon le nombre de victimes. Racine carrée :
  // à l'échelle linéaire, l'Argentine (151) écraserait le Sénégal (1).
  const styleParPays = useMemo(() => {
    const table = new Map<string, { couleur: string; altitude: number }>();
    for (const [id, pays] of byAtlasId) {
      const teinte = CONTINENT_COLORS[pays.continent] ?? "#9AA5B1";
      table.set(id, {
        couleur: surGlobe(teinte, 0.55 + 0.45 * Math.sqrt(pays.count / max)),
        altitude: 0.02,
      });
    }
    return table;
  }, [byAtlasId, max]);

  const capColor = useCallback(
    (f: object) =>
      styleParPays.get(String((f as CountryFeature).id ?? ""))?.couleur ??
      COULEUR_SANS_DONNEE,
    [styleParPays],
  );

  // Les pays sans donnée restent presque plats : l'extrusion construit une
  // paroi verticale par segment de frontière, et c'est là que part l'essentiel
  // des triangles.
  //
  // ⚠️ Presque plats, mais JAMAIS à l'altitude 0. Constaté à l'écran : posée
  // exactement sur la sphère, la surface d'un pays se dispute la profondeur
  // avec elle (z-fighting) et le rendu perce en plaques NOIRES — visibles au
  // Pérou, en Bolivie et le long des Andes.
  // ⚠️ ALTITUDE ET RESOLUTION AGISSENT ENSEMBLE, mesure du 2026-09-05 sur
  // l'Antarctique (trou noir signale a l'usage) :
  //   - resolution seule (24), altitude 0.004 -> trou reduit, pas supprime ;
  //   - altitude seule (0.02), resolution 9   -> trous toujours presents ;
  //   - les DEUX                              -> surface pleine.
  // Le cap d'un grand polygone s'affaisse sous la sphere entre deux
  // subdivisions ; augmenter la resolution reduit la fleche, l'altitude
  // absorbe le reste. 0.02 est l'altitude deja utilisee par les pays qui
  // portent une donnee : aucun decrochage visuel entre les deux familles.
  const polygonAltitude = useCallback(
    (f: object) =>
      styleParPays.get(String((f as CountryFeature).id ?? ""))?.altitude ?? 0.004,
    [styleParPays],
  );

  const polygonLabel = useCallback(
    (f: object) => {
      const feat = f as CountryFeature;
      const pays = byAtlasId.get(String(feat.id ?? ""));
      if (!pays) return `${feat.properties.name} — aucune victime identifiée`;
      return `${pays.name} — ${pays.count} domaine(s) · ${pays.continent}`;
    },
    [byAtlasId],
  );

  const pointLabel = useCallback((p: object) => {
    const point = p as GlobePoint;
    return `${point.name} — ${point.count} domaine(s) · ${point.continent}`;
  }, []);

  const classeBouton =
    "flex h-8 w-8 items-center justify-center rounded-md border border-outline-variant/70 bg-surface-container/90 text-on-surface-variant backdrop-blur transition-colors hover:border-primary/40 hover:bg-surface-bright hover:text-primary";

  return (
    <div
      ref={containerRef}
      className="relative overflow-hidden"
      style={{ height: HAUTEUR }}
    >
      {/* Commandes de zoom. La molette fonctionne déjà, mais elle n'est ni
          visible ni utilisable au pavé tactile sans le savoir. */}
      <div className="absolute right-3 top-3 z-10 flex flex-col gap-1">
        <button onClick={() => zoomer(1 / PAS_ZOOM)} title="Zoomer" aria-label="Zoomer" className={classeBouton}>
          <Icon name="add" className="text-18" />
        </button>
        <button onClick={() => zoomer(PAS_ZOOM)} title="Dézoomer" aria-label="Dézoomer" className={classeBouton}>
          <Icon name="remove" className="text-18" />
        </button>
        <button onClick={recentrer} title="Recentrer la vue" aria-label="Recentrer la vue" className={classeBouton}>
          <Icon name="filter_center_focus" className="text-16" />
        </button>
      </div>

      <Globe
        ref={globeRef}
        width={width}
        height={HAUTEUR}
        backgroundColor="rgba(0,0,0,0)"
        globeMaterial={materiauGlobe}
        // Pas de texture terrestre : elle serait chargée depuis un CDN externe
        // à l'affichage. Ce sont les frontières qui portent l'information.
        showGraticules
        showAtmosphere
        atmosphereColor="#6BA8D6"
        atmosphereAltitude={0.16}
        polygonsData={WORLD.features}
        polygonCapColor={capColor}
        polygonSideColor={cotePolygone}
        polygonStrokeColor={contourPolygone}
        polygonAltitude={polygonAltitude}
        polygonLabel={polygonLabel}
        // Sans cela, chaque mise à jour anime tous les pays pendant une
        // seconde — l'animation coûte plus que le rendu lui-même.
        polygonsTransitionDuration={0}
        polygonCapCurvatureResolution={RESOLUTION_COURBURE}
        pointsData={points}
        pointLat="lat"
        pointLng="lng"
        pointColor="color"
        pointAltitude={0.035}
        pointRadius={0.28}
        pointLabel={pointLabel}
        pointsTransitionDuration={0}
      />
    </div>
  );
}
