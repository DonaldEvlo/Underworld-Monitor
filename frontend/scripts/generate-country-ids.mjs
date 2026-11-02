// Genere src/data/countryAtlasIds.ts : la correspondance entre nos codes ISO2
// et les identifiants numeriques des polygones de `world-atlas`.
//
// Pourquoi une generation plutot qu'une table ecrite a la main : les 170 codes
// ISO numeriques ecrits de memoire produiraient des erreurs muettes -- un
// mauvais code colorerait le mauvais pays sur la carte, sans qu'aucun test ne
// s'en apercoive. Ici la correspondance est DERIVEE des centroides deja
// verifies (src/data/countryCentroids.ts) : pour chaque pays connu, on retient
// le polygone dont le centre est le plus proche, et on imprime la distance
// pour que les cas douteux soient revus.
//
//   node scripts/generate-country-ids.mjs
//
// A relancer si `world-atlas` change de version ou si des pays sont ajoutes
// aux centroides.

import { readFileSync, writeFileSync } from "node:fs";
import { feature } from "topojson-client";

const atlas = JSON.parse(
  readFileSync("node_modules/world-atlas/countries-110m.json", "utf8"),
);
const geo = feature(atlas, atlas.objects.countries);

// Appartenance d'un point a un polygone (lancer de rayon).
//
// ⚠️ Une premiere version appariait au centre le PLUS PROCHE. Verification a
// l'appui, c'etait faux : « Maroc -> France », « France -> Andorre »,
// « Portugal -> Espagne », « Chili -> Argentine », « Malaisie -> Singapour ».
// Le centre d'un pays etendu ou concave n'est pas un bon representant, et les
// Etats-Unis (Alaska) comme la Nouvelle-Zelande (antimeridien) sortaient
// completement. Tester l'APPARTENANCE tranche exactement.
function pointDansAnneau(x, y, anneau) {
  let dedans = false;
  for (let i = 0, j = anneau.length - 1; i < anneau.length; j = i++) {
    const [xi, yi] = anneau[i];
    const [xj, yj] = anneau[j];
    const traverse = yi > y !== yj > y;
    if (traverse && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dedans = !dedans;
  }
  return dedans;
}

function pointDansGeometrie(x, y, geometry) {
  const polygones =
    geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  for (const polygone of polygones) {
    if (!polygone.length) continue;
    // Premier anneau = contour exterieur ; les suivants sont des trous.
    if (!pointDansAnneau(x, y, polygone[0])) continue;
    let dansUnTrou = false;
    for (let t = 1; t < polygone.length; t += 1) {
      if (pointDansAnneau(x, y, polygone[t])) dansUnTrou = true;
    }
    if (!dansUnTrou) return true;
  }
  return false;
}

function distanceAuSommetLePlusProche(x, y, geometry) {
  let min = Infinity;
  const parcourir = (coords) => {
    if (typeof coords[0] === "number") {
      const d = Math.hypot(coords[0] - x, coords[1] - y);
      if (d < min) min = d;
      return;
    }
    for (const sous of coords) parcourir(sous);
  };
  parcourir(geometry.coordinates);
  return min;
}

function centre(geometry) {
  let sx = 0;
  let sy = 0;
  let n = 0;
  const parcourir = (coords) => {
    if (typeof coords[0] === "number") {
      sx += coords[0];
      sy += coords[1];
      n += 1;
      return;
    }
    for (const sous of coords) parcourir(sous);
  };
  parcourir(geometry.coordinates);
  return n ? [sx / n, sy / n] : null;
}

const polygones = geo.features
  .filter((f) => f.id !== undefined && f.geometry)
  .map((f) => ({
    id: String(f.id),
    nom: f.properties.name,
    geometry: f.geometry,
    centre: centre(f.geometry),
  }))
  .filter((p) => p.centre);

// Import du fichier de centroides sans passer par TypeScript : on lit les
// couples ISO2 / lat / lng directement dans le source.
const source = readFileSync("src/data/countryCentroids.ts", "utf8");
const connus = [...source.matchAll(/^\s{2}([A-Z]{2}):\s*\{\s*lat:\s*(-?[\d.]+),\s*lng:\s*(-?[\d.]+),\s*name:\s*"([^"]+)"/gm)].map(
  (m) => ({ iso2: m[1], lat: Number(m[2]), lng: Number(m[3]), nom: m[4] }),
);

const resultat = {};
const douteux = [];
const absents = [];
const replisUtilises = [];
const revendiques = new Set();

// Premiere passe : appartenance stricte. Elle seule fait autorite, et elle
// reserve les polygones avant que les replis ne s'en saisissent.
const restants = [];
for (const pays of connus) {
  const dedans = polygones.filter((p) =>
    pointDansGeometrie(pays.lng, pays.lat, p.geometry),
  );
  if (dedans.length >= 1) {
    // ⚠️ Plusieurs polygones peuvent contenir le point : la Russie et les
    // Fidji franchissent l'antimeridien, si bien que leurs anneaux englobent
    // l'Islande et la Bolivie. Prendre le premier venu peignait l'Islande en
    // Russie. On retient l'ajustement le PLUS SERRE, c'est-a-dire le polygone
    // dont un sommet est le plus proche du point.
    const choisi = dedans
      .map((p) => ({
        p,
        d: distanceAuSommetLePlusProche(pays.lng, pays.lat, p.geometry),
      }))
      .sort((a, b) => a.d - b.d)[0].p;
    if (dedans.length > 1) {
      douteux.push(
        `${pays.iso2} ${pays.nom} : ${dedans.map((c) => c.nom).join(" / ")} -> retenu ${choisi.nom}`,
      );
    }
    resultat[pays.iso2] = choisi.id;
    revendiques.add(choisi.id);
  } else {
    restants.push(pays);
  }
}

for (const pays of restants) {
  // Aucun polygone ne contient le centroide. Cas normal pour un ARCHIPEL : le
  // centre des Philippines ou de la Nouvelle-Zelande tombe en mer, entre les
  // iles. On se rabat alors sur le polygone dont un SOMMET est le plus proche
  // -- et non sur le centre le plus proche, qui donnait « Maroc -> France ».
  let replis = null;
  let distanceMin = Infinity;
  for (const polygone of polygones) {
    // ⚠️ Un polygone appartient a UN SEUL pays. Sans cette regle, un pays
    // absent de l'atlas se rabat sur son voisin : en resolution 110m, les
    // Comores devenaient le Mozambique et Malte devenait l'Italie -- le
    // mauvais pays colorie, en silence. Un polygone deja revendique par
    // containment n'est donc plus disponible.
    if (revendiques.has(polygone.id)) continue;
    const d = distanceAuSommetLePlusProche(pays.lng, pays.lat, polygone.geometry);
    if (d < distanceMin) {
      distanceMin = d;
      replis = polygone;
    }
  }
  // 5 degres : au-dela, on prendrait le voisin plutot que le pays lui-meme.
  if (replis && distanceMin <= 5) {
    resultat[pays.iso2] = replis.id;
    revendiques.add(replis.id);
    replisUtilises.push(
      `${pays.iso2} ${pays.nom} -> ${replis.nom} (${distanceMin.toFixed(1)}° du rivage)`,
    );
    continue;
  }
  absents.push(`${pays.iso2} (${pays.nom})`);
}

const lignes = Object.entries(resultat)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([iso2, id]) => `  ${iso2}: "${id}",`)
  .join("\n");

writeFileSync(
  "src/data/countryAtlasIds.ts",
  `// GENERE par scripts/generate-country-ids.mjs -- ne pas modifier a la main.
//
// Correspondance entre nos codes ISO 3166-1 alpha-2 et les identifiants
// numeriques des polygones de \`world-atlas\` (countries-50m). Derivee des
// centroides plutot qu'ecrite de memoire : un code numerique errone colorerait
// le mauvais pays sur la carte sans qu'aucun test ne le voie.
//
// ${connus.length} pays connus, ${Object.keys(resultat).length} apparies, ${absents.length} absents de l'atlas.

export const COUNTRY_ATLAS_IDS: Record<string, string> = {
${lignes}
};
`,
  "utf8",
);

console.log(`apparies : ${Object.keys(resultat).length}/${connus.length}`);
console.log(`absents de l'atlas (${absents.length}) : ${absents.join(", ") || "aucun"}`);
console.log(`replis archipel (${replisUtilises.length}) :`);
for (const r of replisUtilises) console.log("   " + r);
console.log(`a revoir (${douteux.length}) :`);
for (const d of douteux) console.log("   " + d);
