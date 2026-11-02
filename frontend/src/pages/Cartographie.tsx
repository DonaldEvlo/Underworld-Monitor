import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { statsApi, type GeographyResponse, type GroupStatApi } from "../api/stats";
import { GroupesActifs } from "../components/cartographie/GroupesActifs";
import { MenaceParRegion } from "../components/cartographie/MenaceParRegion";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { CONTINENT_COLORS, COUNTRY_CENTROIDS } from "../data/countryCentroids";
import { COUNTRY_ATLAS_IDS } from "../data/countryAtlasIds";
import type { CountryData, GlobePoint } from "../components/cartographie/GlobeVictimes";
import { chargerGlobe } from "../lib/prechargement";

// ⚠️ Le globe est charge en differe, SEPAREMENT de cette page.
//
// Il embarque three.js et l'atlas mondial, soit l'essentiel du poids. Quand
// tout tenait dans un seul module differe, l'analyste attendait devant une
// page vide : ni les chiffres, ni la repartition par continent, ni
// l'avertissement de couverture ne s'affichaient avant que le moteur 3D soit
// charge. Desormais la page rend immediatement et le globe arrive ensuite.
//
// ⚠️ Le téléchargement part DÈS L'ÉVALUATION DE CE MODULE, pas au premier
// rendu du composant `lazy` : celui-ci n'est rendu qu'une fois la réponse de
// l'API arrivée, ce qui mettait les deux attentes bout à bout.
chargerGlobe().catch(() => undefined);
const GlobeVictimes = lazy(chargerGlobe);

// Dernières données reçues, conservées d'une visite à l'autre : revenir sur la
// carte l'affiche aussitôt, la réponse fraîche remplaçant ensuite l'ancienne.
let cacheGeographie: GeographyResponse | null = null;
let cacheGroupes: GroupStatApi[] = [];

function nomPays(code: string): string {
  return COUNTRY_CENTROIDS[code]?.name ?? code;
}

export function Cartographie() {
  const [data, setData] = useState<GeographyResponse | null>(cacheGeographie);
  const [groupes, setGroupes] = useState<GroupStatApi[]>(cacheGroupes);
  // Groupe sélectionné : le globe ne montre alors QUE ses victimes. C'est ce
  // qui transforme une carte descriptive en outil d'analyse.
  const [groupeSelectionne, setGroupeSelectionne] = useState<string | null>(null);
  const [detailsOuverts, setDetailsOuverts] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loading = data === null && error === null;

  useEffect(() => {
    let vivant = true;
    statsApi
      .geography()
      .then((r) => {
        cacheGeographie = r;
        if (vivant) setData(r);
      })
      .catch((err) => {
        // Avec des données en cache, un échec de rafraîchissement ne masque
        // pas la carte : elle reste lisible, simplement pas à jour.
        if (vivant && !cacheGeographie) setError(err instanceof Error ? err.message : "Erreur inconnue");
      });
    // Les groupes ne bloquent pas la carte : un échec ici laisse la
    // répartition globale utilisable.
    statsApi
      .groups()
      .then((r) => {
        cacheGroupes = r.groups;
        if (vivant) setGroupes(r.groups);
      })
      .catch(() => undefined);
    return () => {
      vivant = false;
    };
  }, []);

  const groupeActif = groupes.find((g) => g.source_id === groupeSelectionne) ?? null;
  // ⚠️ Tout ce qui est affiché à côté du globe suit le MÊME périmètre. Laisser
  // les panneaux sur les chiffres globaux pendant que le globe est filtré
  // ferait lire « AKIRA → Europe 285 », qui est faux.
  const paysAffiches = groupeActif ? groupeActif.countries : (data?.countries ?? []);
  const continentsAffiches = groupeActif ? groupeActif.continents : (data?.continents ?? []);

  const { byAtlasId, points, unmapped, max } = useMemo(() => {
    const index = new Map<string, CountryData>();
    const built: GlobePoint[] = [];
    const orphans: string[] = [];
    if (!data) return { byAtlasId: index, points: built, unmapped: orphans, max: 1 };

    // ⚠️ Le maximum est recalculé sur le PÉRIMÈTRE AFFICHÉ : conserver
    // l'échelle globale écraserait visuellement un groupe modeste jusqu'à le
    // rendre invisible.
    const pays = groupeActif ? groupeActif.countries : data.countries;
    const highest = Math.max(1, ...pays.map((c) => c.victim_domains));

    for (const country of pays) {
      const atlasId = COUNTRY_ATLAS_IDS[country.country_code];
      const centroid = COUNTRY_CENTROIDS[country.country_code];
      if (!atlasId) {
        // Un pays sans polygone disparaitrait de la carte sans un mot : on le
        // compte et on l'affiche plutot que de le laisser tomber.
        orphans.push(country.country_code);
      } else {
        index.set(atlasId, {
          name: centroid?.name ?? country.country_code,
          continent: country.continent,
          count: country.victim_domains,
        });
      }
      if (centroid) {
        // Un repere est pose EN PLUS du polygone : les Seychelles, Monaco ou
        // Macao sont invisibles a l'echelle du globe, et une victime ne doit
        // jamais disparaitre parce que son pays est petit.
        built.push({
          lat: centroid.lat,
          lng: centroid.lng,
          code: country.country_code,
          name: centroid.name,
          continent: country.continent,
          count: country.victim_domains,
          color: CONTINENT_COLORS[country.continent] ?? "#9AA5B1",
        });
      }
    }
    return { byAtlasId: index, points: built, unmapped: orphans, max: highest };
  }, [data, groupeActif]);

  const couverture = data
    ? Math.round((100 * data.located_victim_domains) / Math.max(1, data.total_victim_domains))
    : 0;

  const localisables = groupeActif
    ? groupeActif.located_victim_domains
    : (data?.located_victim_domains ?? 0);

  return (
    <AppLayout title="Cartographie">
      {error && (
        <p className="mb-4 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger la répartition : {error}
        </p>
      )}

      {/* ⚠️ UNE SEULE BANDE DE CADRAGE. Il y en avait quatre empilées — phrase
          de description, avertissement de couverture, note « pays sans
          frontière », bannière « globe filtré sur X » — qui poussaient le
          globe sous la ligne de flottaison. L'avertissement reste obligatoire
          (la carte serait mensongère sans lui), mais il tient en une ligne et
          se déplie pour qui veut le détail. */}
      {data && (
        <div className="mb-3.5 rounded-xl border border-line bg-panel">
          <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 px-4 py-2.5">
            <span className="flex items-center gap-1.5 font-mono-label text-11 text-warn">
              <Icon name="warning" className="text-14" />
              COUVERTURE {couverture} %
            </span>
            <span className="h-4 w-px bg-line" />
            <span className="text-body-sm text-ink">
              {data.located_victim_domains.toLocaleString("fr-FR")} domaines de victimes sur{" "}
              {data.total_victim_domains.toLocaleString("fr-FR")} portent un indice de pays.
            </span>
            <span className="text-body-sm text-ink-dim">
              Les autres sont en <span className="font-mono-data">.com</span> — aucun pays, jamais
              deviné.
            </span>
            <button
              onClick={() => setDetailsOuverts((o) => !o)}
              className="ml-auto flex items-center gap-1.5 font-mono-label text-11 text-signal"
            >
              ce que la carte ne dit pas
              <Icon name={detailsOuverts ? "expand_less" : "expand_more"} className="text-13" />
            </button>
          </div>

          {detailsOuverts && (
            <div className="grid gap-4 border-t border-line-soft px-4 py-3.5 md:grid-cols-3">
              <div>
                <p className="font-mono-data text-20 text-warn">
                  {data.undetermined_victim_domains.toLocaleString("fr-FR")}
                </p>
                <p className="mt-1 text-body-sm text-ink-dim">
                  domaines sans aucun indice de pays (<span className="font-mono-data">.com</span>,{" "}
                  <span className="font-mono-data">.net</span>,{" "}
                  <span className="font-mono-data">.org</span>). Jamais devinés, jamais placés.
                </p>
              </div>
              <div>
                <p className="font-mono-data text-20 text-ink">Am. du Nord</p>
                <p className="mt-1 text-body-sm text-ink-dim">
                  paraît la moins touchée parce que ses organisations sont en{" "}
                  <span className="font-mono-data">.com</span> — un biais de lecture, pas un fait.
                </p>
              </div>
              <div>
                <p className="font-mono-data text-20 text-ink">
                  {unmapped.length} pays
                </p>
                <p className="mt-1 text-body-sm text-ink-dim">
                  {unmapped.length === 0
                    ? "touché n'échappe à l'atlas : tous les pays du périmètre ont une frontière dessinée."
                    : "touchés n'ont pas de frontière dans cet atlas — leur repère reste posé, seul le polygone manque."}
                  {unmapped.length > 0 && (
                    <>
                      {" "}
                      <span className="font-mono-data text-ink">{unmapped.join(", ")}</span>
                    </>
                  )}
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_22.25rem]">
        {/* Pas de `minHeight` : la boite prend exactement la hauteur du globe.
            Elle en imposait une, et la grille l'etirait par-dessus. */}
        <div className="overflow-hidden rounded-[18px] border border-signal/[0.14] bg-panel">
          {/* ⚠️ LE PÉRIMÈTRE AFFICHÉ EST ÉCRIT, ET IL VIT SUR LA CARTE. Une
              carte dont on ignore l'assiette n'est pas interprétable — même
              raison que le périmètre affiché par la synthèse IA et par le test
              de disponibilité des sources. Dans une bannière séparée, il
              sortait de l'écran dès qu'on faisait défiler. */}
          <div
            className={`flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2.5 ${
              groupeActif ? "bg-signal/[0.05]" : ""
            }`}
          >
            {groupeActif ? (
              <button
                onClick={() => setGroupeSelectionne(null)}
                className="flex items-center gap-2 rounded-full border border-signal/45 bg-signal/[0.12] py-0.5 pl-3 pr-1.5 font-mono-label text-11 text-signal"
                title="Revenir à toutes les sources"
              >
                {groupeActif.name}
                <Icon name="close" className="text-13" />
              </button>
            ) : (
              <span className="rounded-full border border-signal/30 bg-signal/[0.09] px-3 py-0.5 font-mono-label text-11 text-signal">
                toutes les sources
              </span>
            )}
            <span className="font-mono-label text-11 text-ink-dim">
              {localisables.toLocaleString("fr-FR")} victimes localisables ·{" "}
              {paysAffiches.length} pays · {continentsAffiches.length} continents
            </span>
            <span className="ml-auto font-mono-label text-11 text-ink-faint">
              échelle recalculée sur ce périmètre
            </span>
          </div>

          {loading ? (
            <p className="p-4 text-body-sm text-ink-dim">Chargement de la répartition…</p>
          ) : points.length === 0 ? (
            // ⚠️ Vide ≠ épargné. L'écran dit POURQUOI il est vide : un groupe
            // peut n'avoir que des victimes en gTLD, donc aucune plaçable.
            <div className="flex flex-col items-center gap-2.5 px-6 py-16 text-center">
              <Icon name="explore_off" className="text-38 text-ink-faint" />
              <p className="font-display text-15 font-bold text-ink">
                Aucune victime localisable
              </p>
              <p className="max-w-sm text-body-sm text-ink-dim">
                {groupeActif
                  ? `${groupeActif.name} a ${groupeActif.victim_domains} victime(s), mais aucune ne porte d'indice de pays.`
                  : "Aucun domaine de victime ne porte d'indice de pays exploitable."}
              </p>
            </div>
          ) : (
            <Suspense
              fallback={<p className="p-4 text-body-sm text-ink-dim">Chargement du globe…</p>}
            >
              <GlobeVictimes byAtlasId={byAtlasId} points={points} max={max} />
            </Suspense>
          )}
        </div>

        <aside className="flex flex-col gap-3">
          {groupes.length > 0 && (
            <GroupesActifs
              groupes={groupes}
              selection={groupeSelectionne}
              onSelect={setGroupeSelectionne}
            />
          )}

          {/* Continents et pays CÔTE À CÔTE : empilés sous un panneau de
              groupes déjà haut, ils repoussaient tout hors de l'écran. */}
          <div className="grid items-start gap-3 sm:grid-cols-2">
            <div className="rounded-[18px] border border-line bg-panel p-3.5">
              <h3 className="font-display text-14 font-bold tracking-tight text-ink">
                Continents
              </h3>
              {groupeActif && (
                <p className="mt-0.5 font-mono-label text-10 text-signal">{groupeActif.name}</p>
              )}
              {continentsAffiches.length ? (
                <ul className="mt-2.5 flex flex-col gap-1.5">
                  {continentsAffiches.map((continent) => (
                    <li key={continent.continent} className="flex items-center gap-2">
                      <span
                        aria-hidden="true"
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ background: CONTINENT_COLORS[continent.continent] ?? "#9AA5B1" }}
                      />
                      {/* ⚠️ PAS DE `truncate` ICI. « Amérique du Sud » et
                          « Amérique du Nord » se coupent tous deux en
                          « Amérique du… » : deux continents distincts
                          deviennent indistinguables. Le libellé passe à la
                          ligne plutôt que de mentir. */}
                      <span className="text-body-sm leading-tight text-ink-dim">
                        {continent.continent}
                      </span>
                      <span className="ml-auto shrink-0 font-mono-data text-body-sm tabular-nums text-ink">
                        {continent.victim_domains}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-body-sm text-ink-dim">Aucune victime localisable.</p>
              )}
            </div>

            <div className="rounded-[18px] border border-line bg-panel p-3.5">
              <h3 className="font-display text-14 font-bold tracking-tight text-ink">Pays</h3>
              {groupeActif && (
                <p className="mt-0.5 font-mono-label text-10 text-signal">{groupeActif.name}</p>
              )}
              {paysAffiches.length ? (
                <ul className="mt-2.5 flex flex-col gap-1.5">
                  {paysAffiches.slice(0, 8).map((country) => (
                    <li key={country.country_code} className="flex items-center gap-2">
                      <span className="text-body-sm leading-tight text-ink-dim">
                        {nomPays(country.country_code)}
                      </span>
                      <span className="ml-auto shrink-0 font-mono-data text-body-sm tabular-nums text-ink">
                        {country.victim_domains}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-body-sm text-ink-dim">Aucun pays identifiable.</p>
              )}
              {paysAffiches.length > 8 && (
                <p className="mt-2 font-mono-label text-10 text-ink-faint">
                  + {paysAffiches.length - 8} autres
                </p>
              )}
            </div>
          </div>
        </aside>
      </div>

      <MenaceParRegion groupes={groupes} onSelectGroupe={setGroupeSelectionne} />
    </AppLayout>
  );
}
