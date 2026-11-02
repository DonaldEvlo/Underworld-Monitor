import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { llmApi, type LLMOption } from "../api/llm";
import { schedulesApi, type ScheduleApi } from "../api/schedules";
import {
  sourcesApi,
  type BatchJobStatus,
  type CollectResult,
  type SourceApi,
} from "../api/sources";
import { AppLayout } from "../components/layout/AppLayout";
import { LlmChatPanel } from "../components/llm/LlmChatPanel";
import { TestDisponibilite } from "../components/sources/TestDisponibilite";
import { Icon } from "../components/ui/Icon";
import { collectorLabels, sourceTypeLabels } from "../lib/taxonomy";
import { useRequete } from "../hooks/useRequete";

function collectorLabel(name: string | null | undefined): string | null {
  if (!name) return null;
  return collectorLabels[name] ?? name;
}

const BATCH_STORAGE_KEY = "collecte:activeBatchId";
const POLL_INTERVAL_MS = 1500;
const PANNEAU = "rounded-[18px] border border-line bg-panel p-4";

// Durée lisible : « 45 s », « 3 min », « 1 h 12 ».
function dureeLisible(secondes: number): string {
  if (secondes < 60) return `${secondes} s`;
  const minutes = Math.round(secondes / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

/**
 * Collecte : les gestes manuels (lancer, tester). Ce qui tourne tout seul vit
 * sur la page Planification.
 *
 * ⚠️ PAS D'« ÉTAT DU CIRCUIT TOR » dans le bandeau, bien que la maquette en
 * montre un : aucun point de l'API ne le mesure. Afficher « actif · 3 sauts »
 * serait décoratif — et un indicateur de sécurité décoratif est pire que pas
 * d'indicateur. Le bandeau ne dit que ce qui est connu.
 */
export function Collecte() {
  const sourcesReq = useRequete(() => sourcesApi.list(), []);
  const sources: SourceApi[] = sourcesReq.donnees ?? [];
  // Par défaut la première source ; un choix de l'analyste l'emporte.
  const [choixSource, setSelectedId] = useState<string | null>(null);
  const selectedId = choixSource ?? sources[0]?.id ?? "";
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CollectResult | null>(null);
  const loadError = sourcesReq.erreur;
  const tachesReq = useRequete(async () => (await schedulesApi.list()).schedules, []);
  const taches: ScheduleApi[] = tachesReq.donnees ?? [];
  const modeleReq = useRequete(async () => {
    const [actuel, options] = await Promise.all([llmApi.getSelected(), llmApi.options()]);
    return options.find((o) => o.id === actuel.model) ?? null;
  }, []);
  const modele: LLMOption | null = modeleReq.donnees;

  const [batchId, setBatchId] = useState<string | null>(() => localStorage.getItem(BATCH_STORAGE_KEY));
  const [batchStatus, setBatchStatus] = useState<BatchJobStatus | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);

  // Suit le job de collecte groupée. Reprend au montage si un `batch_id` est
  // en cours (localStorage) : la collecte tourne côté serveur, quitter l'onglet
  // et y revenir retrouve la progression exacte.
  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    async function poll() {
      try {
        const status = await sourcesApi.getCollectAllStatus(batchId!);
        if (cancelled) return;
        setBatchStatus(status);
        if (status.status === "done" && interval) {
          clearInterval(interval);
          interval = null;
        }
      } catch {
        if (cancelled) return;
        localStorage.removeItem(BATCH_STORAGE_KEY);
        setBatchId(null);
        setBatchStatus(null);
        if (interval) clearInterval(interval);
      }
    }

    void poll();
    interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [batchId]);

  const selectedSource = sources.find((s) => s.id === selectedId);
  const activeCount = sources.filter((s) => s.active).length;
  const runningBatch = batchStatus?.status === "running";
  // Seules les entrées ACTIVES annoncent un passage : une planification
  // suspendue ne déclenchera rien.
  const planifiees = taches.filter((t) => t.enabled);

  async function handleCollect() {
    if (!selectedId) return;
    setRunning(true);
    setResult(null);
    try {
      setResult(await sourcesApi.collect(selectedId));
    } catch (err) {
      setResult({ success: false, error: err instanceof Error ? err.message : "Erreur inconnue", saved_count: 0 });
    } finally {
      setRunning(false);
    }
  }

  async function handleCollectAll() {
    setBatchError(null);
    setBatchStatus(null);
    try {
      const status = await sourcesApi.startCollectAll();
      localStorage.setItem(BATCH_STORAGE_KEY, status.batch_id);
      setBatchStatus(status);
      setBatchId(status.batch_id);
    } catch (err) {
      setBatchError(err instanceof Error ? err.message : "Erreur inconnue");
    }
  }

  return (
    <AppLayout title="Collecte">
      <section className="pulse-panel mb-3.5 flex flex-wrap items-center gap-x-7 gap-y-3 px-5 py-4">
        <div>
          <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">Collectes automatiques</p>
          <Link to="/planification" className="mt-0.5 block font-display text-18 font-bold tracking-tight text-ink hover:text-signal">
            {planifiees.length > 0 ? planifiees[0].schedule : "aucune planification active"}
            <span className="ml-2 font-mono-label text-11 font-normal text-signal">planification →</span>
          </Link>
        </div>
        <span className="hidden h-10 w-px bg-line md:block" />
        <div>
          <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">En file</p>
          <p className="mt-1 font-mono-data text-15 text-ink">
            {activeCount} source(s) active(s)
            {runningBatch && batchStatus ? ` · ${batchStatus.done}/${batchStatus.total} traitées` : ""}
          </p>
        </div>
        <button
          onClick={() => void handleCollectAll()}
          disabled={runningBatch || activeCount === 0}
          className="ml-auto flex items-center gap-2 rounded-[10px] bg-signal px-3.5 py-2 text-13 font-semibold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {runningBatch && <Icon name="progress_activity" className="animate-spin text-15" />}
          {runningBatch ? `Collecte en cours (${batchStatus?.done}/${batchStatus?.total})` : `Collecter les ${activeCount} sources actives`}
        </button>
      </section>

      {loadError && (
        <p className="mb-3.5 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger les sources : {loadError}
        </p>
      )}

      <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_21.5rem]">
        <div className="flex flex-col gap-3.5">
          <div className="grid items-start gap-3.5 lg:grid-cols-[20rem_minmax(0,1fr)]">
            <section className={PANNEAU}>
              <h2 className="font-display text-15 font-bold tracking-tight text-ink">Collecte manuelle</h2>
              <label className="mb-1 mt-3 block font-caption text-caption text-ink-faint">Source</label>
              <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)} className="mb-3 w-full rounded-lg border border-line bg-panel-sunken px-3 py-2 text-body-sm text-ink outline-none focus:border-signal/60">
                {sources.length === 0 && <option value="">Aucune source disponible</option>}
                {sources.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} — {sourceTypeLabels[s.type]}
                  </option>
                ))}
              </select>
              {selectedSource && (
                <p className="mb-3 break-all font-mono-label text-10.5 text-ink-faint">
                  {selectedSource.url} · trafic routé via Tor
                </p>
              )}
              <div className="flex flex-col gap-2">
                <button onClick={() => void handleCollect()} disabled={!selectedId || running} className="flex w-full items-center justify-center gap-2 rounded-[10px] bg-signal px-4 py-2 text-body-sm font-semibold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-50">
                  {running && <Icon name="progress_activity" className="animate-spin text-15" />}
                  {running ? "Collecte en cours…" : "Lancer la collecte"}
                </button>
              </div>
            </section>

            <section className={PANNEAU}>
              <h2 className="font-display text-15 font-bold tracking-tight text-ink">Résultat</h2>
              {!result && !running && <p className="mt-2 text-body-sm text-ink-dim">Aucune collecte manuelle lancée pour l&apos;instant.</p>}
              {result && !result.success && (
                <div className="mt-3 rounded-xl border border-critical/35 bg-critical/[0.07] p-3">
                  <p className="font-mono-label text-11 uppercase text-critical">Échec de la collecte</p>
                  <p className="mt-1 text-body-sm text-ink-dim">{result.error}</p>
                </div>
              )}
              {result?.success && (
                <div className="mt-3 flex flex-col gap-3">
                  <div className="flex flex-wrap gap-6">
                    <div>
                      <p className="font-caption text-caption text-ink-faint">Longueur extraite</p>
                      <p className="font-mono-data text-17 text-signal">{result.text_length} car.</p>
                    </div>
                    <div>
                      <p className="font-caption text-caption text-ink-faint">Documents nouveaux</p>
                      <p className="font-mono-data text-17 text-signal">{result.saved_count}</p>
                    </div>
                    {result.collector && (
                      <div>
                        <p className="font-caption text-caption text-ink-faint">Collecteur</p>
                        <p className="mt-1 font-mono-data text-body-sm text-ink">{collectorLabel(result.collector)}</p>
                      </div>
                    )}
                  </div>
                  {result.saved_count > 0 && (
                    <div className="flex flex-wrap gap-2">
                      <Link to="/documents" className="rounded-[10px] border border-signal/30 bg-signal/10 px-3 py-1.5 text-body-sm text-signal">Voir les documents</Link>
                      <Link to="/detections" className="rounded-[10px] border border-line px-3 py-1.5 text-body-sm text-ink">Voir les détections</Link>
                    </div>
                  )}
                  {result.matched_keywords && result.matched_keywords.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      <span className="font-caption text-caption text-ink-faint">Watchlist</span>
                      {result.matched_keywords.map((kw) => (
                        <span key={kw} className="rounded-md border border-signal/30 bg-signal/10 px-2 py-0.5 font-mono-data text-11 text-signal">{kw}</span>
                      ))}
                    </div>
                  )}
                  <pre className="custom-scrollbar max-h-[26rem] overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-panel-sunken p-3 font-mono-data text-12 text-ink-dim">
                    {result.text}
                  </pre>
                </div>
              )}
            </section>
          </div>

          <section className={PANNEAU}>
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">Disponibilité des sources</h2>
            <p className="mb-3 mt-1 text-body-sm text-ink-dim">
              Vérifie via Tor que les sources répondent encore, sans rien collecter.
            </p>
            <TestDisponibilite
              nbActives={activeCount}
              nbTotal={sources.length}
              sourceSelectionnee={selectedSource ? { id: selectedSource.id, name: selectedSource.name } : null}
            />
          </section>

          {result?.success && result.text && (
            <LlmChatPanel key={result.text} onSend={(query) => llmApi.analyze(result.text!, query).then((r) => r.response)} />
          )}

          <section className={PANNEAU}>
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="font-display text-15 font-bold tracking-tight text-ink">Collecte groupée</h2>
              <p className="font-mono-label text-11 text-ink-faint">
                jusqu&apos;à 5 sources en parallèle
              </p>
            </div>

            {batchError && <p className="mt-3 text-body-sm text-critical">{batchError}</p>}

            {!batchStatus && (
              <p className="mt-2 text-body-sm text-ink-dim">Aucune collecte groupée en cours. Lancez-la depuis le bandeau.</p>
            )}

            {batchStatus && (
              <>
                <div className="mb-2 mt-3 flex items-center gap-3">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-panel-raised">
                    <div className="h-full bg-signal transition-all" style={{ width: `${(batchStatus.done / Math.max(batchStatus.total, 1)) * 100}%` }} />
                  </div>
                  <span className="font-mono-data text-body-sm text-ink-dim">
                    {batchStatus.done}/{batchStatus.total}
                  </span>
                </div>
                {/* ⚠️ L'estimation n'est affichée que si des durées passées sont
                    connues, AVEC le nombre de sources sur lequel elle repose :
                    bâtie sur 1 source sur 24, elle est très optimiste. */}
                {batchStatus.status === "running" && batchStatus.eta_seconds !== null && (
                  <p className="mb-2 font-mono-label text-11 text-ink-dim">
                    Environ {dureeLisible(batchStatus.eta_seconds)} restantes · d&apos;après {batchStatus.eta_known_sources} source(s) chronométrée(s) sur {batchStatus.eta_total_sources}
                  </p>
                )}
                {batchStatus.status === "running" && batchStatus.eta_seconds === null && (
                  <p className="mb-2 font-mono-label text-11 text-ink-faint">Temps restant inconnu — aucune collecte précédente chronométrée.</p>
                )}
                <div className="custom-scrollbar max-h-64 overflow-y-auto rounded-xl border border-line">
                  <table className="w-full text-left text-body-sm">
                    <thead className="sticky top-0 bg-panel font-mono-label text-10 uppercase tracking-[0.12em] text-ink-faint">
                      <tr>
                        <th className="px-3 py-2">Source</th>
                        <th className="px-3 py-2">Statut</th>
                        <th className="px-3 py-2 text-right">Nouveaux</th>
                        <th className="px-3 py-2 text-right">Détail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batchStatus.items.map((item) => (
                        <tr key={item.source_id} className="border-t border-line-soft">
                          <td className="px-3 py-2 text-ink">{item.name}</td>
                          <td className="px-3 py-2">{item.success ? <span className="text-signal">succès</span> : <span className="text-critical">échec</span>}</td>
                          <td className="px-3 py-2 text-right font-mono-data text-ink-dim">
                            {!item.success ? (
                              "—"
                            ) : item.saved_count > 0 ? (
                              item.saved_count
                            ) : (
                              // `saved_count` compte les documents NOUVEAUX : 0 sur
                              // une source qui a répondu = « déjà tout en base ».
                              <span title="La source a répondu, mais tout était déjà en base (déduplication par empreinte)">0 nouveau</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right font-mono-data text-11 text-ink-dim">{item.success ? `${item.text_length} car.` : item.error}</td>
                        </tr>
                      ))}
                      {runningBatch &&
                        Array.from({ length: batchStatus.total - batchStatus.items.length }).map((_, i) => (
                          <tr key={`pending-${i}`} className="border-t border-line-soft opacity-40">
                            <td className="px-3 py-2 text-ink-dim" colSpan={4}>
                              en attente…
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {batchStatus?.status === "done" && batchStatus.items.some((i) => i.success) && (
              <div className="mt-3">
                <LlmChatPanel key={batchStatus.batch_id} placeholder="Poser une question sur l'ensemble des pages collectées…" onSend={(query) => llmApi.analyzeBatch(batchStatus.batch_id, query).then((r) => r.response)} />
              </div>
            )}
          </section>
        </div>

        <aside className="flex flex-col gap-3.5">
          <section className="pulse-panel p-4">
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">Modèle LLM</h2>
            <div className="mt-2.5 flex flex-col gap-1.5 font-mono-data text-11">
              <div className="flex justify-between gap-3">
                <span className="text-ink-dim">modèle</span>
                <span className="truncate text-ink">{modele?.label ?? "—"}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-ink-dim">fenêtre lue</span>
                <span className="text-warn">12 000 car.</span>
              </div>
              <div className="flex justify-between gap-3">
                <span className="text-ink-dim">exécution</span>
                <span className={modele && modele.provider !== "ollama" ? "text-warn" : "text-ink"}>
                  {modele ? (modele.provider === "ollama" ? "locale" : "distante") : "—"}
                </span>
              </div>
            </div>
            <p className="mt-2.5 rounded-xl border border-warn/30 bg-panel-sunken p-2.5 text-12 text-warn">
              Un document plus long que la fenêtre est résumé sur un extrait — le résumé le dit.
            </p>
            <Link to="/settings" className="mt-2.5 block font-mono-label text-11 text-signal">
              changer de modèle →
            </Link>
          </section>

          <section className="rounded-[18px] border border-line bg-panel p-4">
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">Enrichissements externes</h2>
            <div className="mt-2.5 flex flex-col gap-2">
              <div className="rounded-xl border border-line bg-panel-sunken p-2.5">
                <p className="text-body-sm text-ink">IntelX · corroboration</p>
                <p className="mt-0.5 font-mono-label text-10 text-ink-faint">quota limité — à utiliser avec parcimonie</p>
              </div>
              <div className="rounded-xl border border-line bg-panel-sunken p-2.5">
                <p className="text-body-sm text-ink">Certificats · sous-domaines</p>
                <p className="mt-0.5 font-mono-label text-10 text-ink-faint">appels en clair, hors circuit Tor</p>
              </div>
              <div className="rounded-xl border border-line bg-panel-sunken p-2.5">
                <p className="text-body-sm text-ink">RansomLook · corroboration</p>
                <p className="mt-0.5 font-mono-label text-10 text-ink-faint">un appel par passe d&apos;alerting, en clair</p>
              </div>
            </div>
            <p className="mt-2.5 font-mono-label text-10 text-ink-faint">
              la collecte, elle, passe toujours par Tor
            </p>
          </section>
        </aside>
      </div>
    </AppLayout>
  );
}
