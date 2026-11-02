import { useEffect, useState } from "react";
import { dreadSearchApi, type DreadSearchJobStatus } from "../../api/dread";
import { Icon } from "../ui/Icon";

const JOB_STORAGE_KEY = "watchlist:activeDreadSearchJobId";
const POLL_INTERVAL_MS = 1500;

export function DreadSearchPanel() {
  const [jobId, setJobId] = useState<string | null>(() => localStorage.getItem(JOB_STORAGE_KEY));
  const [status, setStatus] = useState<DreadSearchJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  // Reprend le suivi si un job est déjà en cours (localStorage) : la recherche
  // tourne côté serveur (BackgroundTasks), donc quitter cette page et y revenir
  // retrouve la progression exacte.
  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    async function poll() {
      try {
        const s = await dreadSearchApi.getStatus(jobId!);
        if (cancelled) return;
        setStatus(s);
        if (s.status === "done" && interval) {
          clearInterval(interval);
          interval = null;
        }
      } catch {
        if (cancelled) return;
        localStorage.removeItem(JOB_STORAGE_KEY);
        setJobId(null);
        setStatus(null);
        if (interval) clearInterval(interval);
      }
    }

    void poll();
    interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [jobId]);

  const running = status?.status === "running";
  const totalHits = status?.items.reduce((sum, item) => sum + item.hits.length, 0) ?? 0;

  async function handleRun() {
    setError(null);
    setStatus(null);
    try {
      const s = await dreadSearchApi.run();
      localStorage.setItem(JOB_STORAGE_KEY, s.job_id);
      setStatus(s);
      setJobId(s.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    }
  }

  return (
    <div className="rounded-lg border border-outline-variant bg-surface-container p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-headline-md text-headline-md text-on-surface">
          <Icon name="travel_explore" className="text-primary" />
          Recherche Dread par mot-clé
        </h3>
        <button
          onClick={() => void handleRun()}
          disabled={running}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-body-sm font-bold text-on-primary transition-all hover:opacity-90 disabled:opacity-50"
        >
          <Icon name={running ? "progress_activity" : "play_arrow"} className={running ? "animate-spin" : ""} />
          {running ? `Recherche en cours... (${status?.done}/${status?.total})` : "Lancer la recherche"}
        </button>
      </div>
      <p className="mb-4 text-11 text-on-surface-variant">
        Cherche chaque mot-clé actif dans Dread, en tâche de fond.
      </p>

      {error && (
        <p className="mb-4 rounded border border-error/40 bg-error-container/20 p-3 text-body-sm text-error">
          {error}
        </p>
      )}

      {status && (
        <>
          <div className="mb-3 flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-container-highest">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${(status.done / Math.max(status.total, 1)) * 100}%` }}
              />
            </div>
            <span className="font-mono-data text-body-sm text-on-surface-variant">
              {status.done}/{status.total}
            </span>
          </div>

          {status.status === "done" && (
            <p className="mb-3 text-body-sm text-on-surface-variant">
              {totalHits} résultat{totalHits !== 1 ? "s" : ""} trouvé{totalHits !== 1 ? "s" : ""} au total.
            </p>
          )}

          <div className="custom-scrollbar max-h-[32rem] space-y-2 overflow-y-auto">
            {status.items.map((item) => (
              <div key={item.keyword} className="rounded border border-outline-variant">
                <button
                  onClick={() => setExpanded(expanded === item.keyword ? null : item.keyword)}
                  className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-surface-container-high"
                >
                  <span className="flex items-center gap-2">
                    <span className="rounded border border-outline-variant bg-surface-container-lowest px-2 py-0.5 font-mono-data text-mono-data text-on-surface">
                      {item.keyword}
                    </span>
                    {item.success ? (
                      <span className="text-body-sm text-on-surface-variant">
                        {item.hits.length} résultat{item.hits.length !== 1 ? "s" : ""}
                      </span>
                    ) : (
                      <span className="text-body-sm text-error">{item.error ?? "Échec"}</span>
                    )}
                  </span>
                  <Icon name={expanded === item.keyword ? "expand_less" : "expand_more"} />
                </button>

                {expanded === item.keyword && item.hits.length > 0 && (
                  <div className="divide-y divide-outline-variant/30 border-t border-outline-variant">
                    {item.hits.map((hit) => (
                      <div key={hit.link} className="p-3">
                        <p className="font-bold text-on-surface" title={hit.link}>
                          {hit.title}
                        </p>
                        <p className="font-mono-label text-10 text-on-surface-variant">{hit.link}</p>
                        <p className="mt-1 text-10 text-on-surface-variant">
                          {hit.subdread && <span>{hit.subdread} </span>}
                          {hit.author && <span>• {hit.author} </span>}
                          {hit.date && <span>• {hit.date}</span>}
                        </p>
                        {hit.snippet && (
                          <p className="mt-1 text-body-sm text-on-surface-variant">{hit.snippet}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {running &&
              Array.from({ length: status.total - status.items.length }).map((_, i) => (
                <div key={`pending-${i}`} className="rounded border border-outline-variant px-3 py-2 opacity-40">
                  En attente...
                </div>
              ))}
          </div>
        </>
      )}
    </div>
  );
}
