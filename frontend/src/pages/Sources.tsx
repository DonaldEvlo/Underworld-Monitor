import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { sourcesApi, type SourceApi } from "../api/sources";
import { AppLayout } from "../components/layout/AppLayout";
import { PastilleTest, TestDisponibilite } from "../components/sources/TestDisponibilite";
import { Icon } from "../components/ui/Icon";
import { LectureSeule } from "../components/ui/LectureSeule";
import { useTestSources } from "../hooks/useTestSources";
import { useAuth } from "../context/auth-context";
import { peutAdministrer } from "../lib/roles";
import { StatusDot } from "../components/ui/StatusDot";
import { ageRelatif } from "../lib/alertes";
import { sourceTypeIcons, sourceTypeLabels } from "../lib/taxonomy";
import { dateHeure } from "../lib/format";
import { useRequete } from "../hooks/useRequete";
import { NewSourceForm } from "../components/sources/FormulaireSource";
import { EditSourceRow } from "../components/sources/LigneSourceEdition";
import { ImportExportControls } from "../components/sources/ImportExportSources";
import { GithubImportControls } from "../components/sources/ImportGithubSources";
import { ChangementsAdresse } from "../components/sources/ChangementsAdresse";
import type { SourcePrefill } from "../components/sources/sourcesTypes";









export function Sources() {
  const location = useLocation();
  const navigate = useNavigate();
  const prefill = (location.state as { prefill?: SourcePrefill } | null)?.prefill ?? null;

  const requete = useRequete(() => sourcesApi.list(), []);
  const sources: SourceApi[] = requete.donnees ?? [];
  const loading = requete.chargement;
  const reload = requete.recharger;
  // Erreur d'une ACTION (suppression, bascule) : distincte de l'erreur de
  // chargement, qui disparaît d'elle-même au rechargement suivant.
  const [erreurAction, setLoadError] = useState<string | null>(null);
  const loadError = requete.erreur ?? erreurAction;
  const modifierSources = requete.modifier;
  const setSources = (fn: (prev: SourceApi[]) => SourceApi[]) =>
    modifierSources((precedent) => fn(precedent ?? []));
  const [editingId, setEditingId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  // Test de disponibilité partagé avec la page Collecte : l'état de chaque
  // source s'affiche dans sa ligne, au fil du test.
  const { job: testJob } = useTestSources();
  const etatTestParSource = new Map(testJob?.entries.map((e) => [e.source_id, e]) ?? []);
  // Declarer, modifier, supprimer, tester : tout cela est en PEUT_ADMINISTRER
  // cote serveur. La LISTE, elle, est lisible par l'analyste — il doit
  // savoir d'ou vient un document pour pouvoir le verifier.
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);

  useEffect(() => {
    // Nettoie le state de navigation après consommation : un retour arrière
    // ou un rechargement ne doit pas rouvrir le formulaire prérempli.
    if (prefill) {
      void navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  async function handleDelete(id: string) {
    try {
      await sourcesApi.remove(id);
      setSources((prev) => prev.filter((s) => s.id !== id));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Suppression impossible");
    }
  }

  async function handleToggleActive(source: SourceApi) {
    try {
      const updated = await sourcesApi.update(source.id, { active: !source.active });
      setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Modification impossible");
    }
  }

  // Filtrage côté client : toutes les sources sont déjà chargées. L'URL est
  // cherchée aussi — plusieurs sources portent le MÊME nom et ne diffèrent
  // que par leur adresse .onion (miroirs).
  const normalizedSearch = search.trim().toLowerCase();
  const visibleSources = normalizedSearch
    ? sources.filter(
        (s) =>
          s.name.toLowerCase().includes(normalizedSearch) ||
          s.url.toLowerCase().includes(normalizedSearch) ||
          sourceTypeLabels[s.type].toLowerCase().includes(normalizedSearch),
      )
    : sources;

  // ⚠️ Synthèse calculée sur ce que l'API expose RÉELLEMENT. La maquette
  // montrait latence et documents/24 h : ils ne sont pas stockés, les inventer
  // ferait passer une estimation pour une mesure.
  const actives = sources.filter((s) => s.active).length;
  const jamais = sources.filter((s) => s.active && !s.last_collected_at).length;
  const js = sources.filter((s) => s.requires_js).length;
  const cartes = [
    { n: actives, label: "sources actives — collectées à chaque passage", ton: "text-signal", cadre: "border-signal/25" },
    { n: sources.length - actives, label: "inactives — conservées, jamais collectées", ton: "text-ink", cadre: "border-line" },
    { n: jamais, label: "actives jamais collectées", ton: jamais > 0 ? "text-warn" : "text-ink", cadre: jamais > 0 ? "border-warn/30" : "border-line" },
    { n: js, label: "exigent un navigateur (JS)", ton: "text-info", cadre: "border-line" },
  ];

  return (
    <AppLayout title="Sources" searchPlaceholder="rechercher une source" searchValue={search} onSearchChange={setSearch}>
      {!admin && <LectureSeule quoi="la gestion des sources" />}

      {loadError && (
        <p className="mb-3.5 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger les sources : {loadError}. Le backend est-il démarré ?
        </p>
      )}

      {!loading && sources.length === 0 && !loadError ? (
        <div className="flex flex-col items-center gap-2 rounded-[18px] border border-signal/[0.14] bg-panel px-8 py-12 text-center">
          <p className="font-display text-19 font-bold text-ink">Aucune source déclarée</p>
          <p className="max-w-lg text-body-sm text-ink-dim">
            Rien n&apos;est collecté. Déclarez au moins un site de fuite, puis planifiez un
            passage depuis Collecte &amp; planification.
          </p>
          {admin && (
            <div className="mt-3 flex w-full max-w-3xl flex-col items-center gap-3">
              <NewSourceForm onCreated={(s) => setSources((p) => [s, ...p])} prefill={prefill} />
              <div className="w-full max-w-sm">
                <ImportExportControls onImported={reload} />
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3.5">
          <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
            {cartes.map((c) => (
              <div key={c.label} className={`rounded-[18px] border bg-panel px-4 py-3.5 ${c.cadre}`}>
                <p className={`font-mono-data text-24 tabular-nums ${c.ton}`}>{c.n}</p>
                <p className="mt-0.5 text-body-sm text-ink-dim">{c.label}</p>
              </div>
            ))}
          </div>

          <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_21.5rem]">
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <p className="font-mono-label text-11 text-ink-faint">
                  {normalizedSearch
                    ? `${visibleSources.length} source(s) sur ${sources.length}`
                    : `${sources.length} source(s) déclarée(s)`}{" "}
                  {admin ? " · cliquer l’état active ou désactive la collecte" : ""}
                </p>
                {admin && (
                  <div className="ml-auto">
                    <NewSourceForm onCreated={(s) => setSources((p) => [s, ...p])} prefill={prefill} />
                  </div>
                )}
              </div>

              <div className="overflow-hidden rounded-[18px] border border-line bg-panel">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] border-collapse text-left">
                    <thead>
                      <tr className="border-b border-line">
                        {["Source", "État", "Dernière collecte", ""].map((h) => (
                          <th key={h} className="px-4 py-2.5 font-mono-label text-10 font-medium uppercase tracking-[0.12em] text-ink-faint">
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {!loading && visibleSources.length === 0 && (
                        <tr>
                          <td colSpan={4} className="px-4 py-8 text-center text-body-sm text-ink-dim">
                            Aucune source ne correspond à « {search.trim()} ».
                          </td>
                        </tr>
                      )}
                      {visibleSources.map((source) =>
                        editingId === source.id ? (
                          <EditSourceRow
                            key={source.id}
                            source={source}
                            onCancel={() => setEditingId(null)}
                            onSaved={(updated) => {
                              setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
                              setEditingId(null);
                            }}
                          />
                        ) : (
                          <tr key={source.id} className="group border-b border-line-soft transition-colors last:border-b-0 hover:bg-[#111925]">
                            <td className="px-4 py-3">
                              <div className="flex min-w-0 items-center gap-3">
                                <Icon name={sourceTypeIcons[source.type]} className="text-17 text-ink-dim" />
                                <div className="min-w-0">
                                  <p className="truncate text-13 font-semibold text-ink">{source.name}</p>
                                  {/* Affichée, jamais cliquable : un `.onion` exige Tor. */}
                                  <p className="truncate font-mono-label text-10.5 text-ink-faint">{source.url}</p>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              {/* ⚠️ Sans le droit, l'état reste AFFICHÉ — il dit si la
                                  source alimente le corpus, information dont l'analyste a
                                  besoin. Seule la bascule disparaît. */}
                              {admin ? (
                                <button
                                  onClick={() => void handleToggleActive(source)}
                                  title={source.active ? "Cliquer pour désactiver (ne sera plus collectée)" : "Cliquer pour activer (sera collectée)"}
                                  className="flex items-center gap-2 rounded-md px-1.5 py-0.5 transition-colors hover:bg-panel-raised"
                                >
                                  <StatusDot color={source.active ? "ok" : "dim"} />
                                  <span className={`font-mono-data text-11 ${source.active ? "text-ok" : "text-ink-faint"}`}>
                                    {source.active ? "active" : "inactive"}
                                  </span>
                                </button>
                              ) : (
                                <span className="flex items-center gap-2 px-1.5 py-0.5">
                                  <StatusDot color={source.active ? "ok" : "dim"} />
                                  <span className={`font-mono-data text-11 ${source.active ? "text-ok" : "text-ink-faint"}`}>
                                    {source.active ? "active" : "inactive"}
                                  </span>
                                </span>
                              )}
                              <p className="mt-0.5 pl-1.5 font-mono-label text-10 text-ink-faint">
                                {source.requires_js ? "navigateur (JS)" : sourceTypeLabels[source.type]}
                              </p>
                              {etatTestParSource.has(source.id) && (
                                <p className="mt-0.5 pl-1.5">
                                  <PastilleTest entree={etatTestParSource.get(source.id)!} />
                                </p>
                              )}
                            </td>
                            <td className="px-4 py-3 font-mono-data text-11 text-ink-dim" title={source.last_collected_at ? dateHeure(source.last_collected_at) : undefined}>
                              {source.last_collected_at ? (
                                ageRelatif(source.last_collected_at)
                              ) : (
                                <span className={source.active ? "text-warn" : "text-ink-faint"}>jamais</span>
                              )}
                            </td>
                            <td className="px-4 py-3 text-right">
                              {admin && (
                                <div className="flex justify-end gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                                  <button onClick={() => setEditingId(source.id)} className="rounded-md p-1.5 text-ink-dim hover:bg-signal/15 hover:text-signal" title="Modifier">
                                    <Icon name="edit" className="text-16" />
                                  </button>
                                  <button onClick={() => void handleDelete(source.id)} className="rounded-md p-1.5 text-ink-dim hover:bg-critical/15 hover:text-critical" title="Supprimer">
                                    <Icon name="delete" className="text-16" />
                                  </button>
                                </div>
                              )}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <aside className="flex flex-col gap-3.5">
              <section className="rounded-[18px] border border-warn/30 bg-panel p-4">
                <h2 className="font-display text-15 font-bold tracking-tight text-ink">Injoignable n&apos;est pas morte</h2>
                <p className="mt-1 text-body-sm text-ink-dim">
                  Aucune source n&apos;est désactivée automatiquement.
                </p>
                <div className="mt-3">
                  <TestDisponibilite nbActives={actives} nbTotal={sources.length} afficherListe={false} />
                </div>
              </section>

              <ChangementsAdresse admin={admin} onBascule={reload} />

              {admin && (
              <section className="rounded-[18px] border border-line bg-panel p-4">
                <h2 className="font-display text-15 font-bold tracking-tight text-ink">Enrichir le catalogue</h2>
                <p className="mb-3 mt-1 text-body-sm text-ink-dim">
                  Seules les adresses qui répondent via Tor sont ajoutées, et toujours inactives :
                  l&apos;activation reste un choix.
                </p>
                <div className="flex flex-col gap-2.5">
                  <GithubImportControls onImported={reload} />
                  <ImportExportControls onImported={reload} />
                </div>
              </section>
              )}
            </aside>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
