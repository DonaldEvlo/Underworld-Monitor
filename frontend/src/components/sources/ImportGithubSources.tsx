import { useEffect, useState } from "react";
import { sourcesApi, type GithubImportJobStatus } from "../../api/sources";

const GITHUB_POLL_INTERVAL_MS = 3000;

export function GithubImportControls({ onImported }: { onImported: () => void }) {
  const [job, setJob] = useState<GithubImportJobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const timer = setTimeout(async () => {
      try {
        const updated = await sourcesApi.getGithubImportStatus(job.job_id);
        setJob(updated);
        if (updated.status === "done") onImported();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erreur de suivi du job");
      }
    }, GITHUB_POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [job, onImported]);

  async function handleStart() {
    setError(null);
    try {
      setJob(await sourcesApi.startGithubImport());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Échec du démarrage de l'import");
    }
  }

  const running = job !== null && job.status !== "done" && job.status !== "error";

  return (
    <div className="flex flex-col gap-1.5">
      <button
        onClick={() => void handleStart()}
        disabled={running}
        className="rounded-[10px] border border-line bg-panel-sunken px-3 py-2 text-body-sm text-ink transition-colors hover:border-signal/35 disabled:opacity-60"
        title="Récupère la liste publique deepdarkCTI, teste les nouvelles adresses via Tor et n'ajoute que celles qui répondent — ne touche jamais aux sources déjà en base"
      >
        {running ? "Import en cours…" : "Importer depuis la liste publique (GitHub)"}
      </button>
      {job && (
        <p className="font-mono-label text-10.5 leading-4 text-ink-dim">
          {job.status === "fetching" && "Récupération de la liste…"}
          {job.status === "testing" && (
            <>
              Test via Tor : {job.tested}/{job.new_candidates} ({job.created.length} joignable
              {job.created.length > 1 ? "s" : ""})
            </>
          )}
          {job.status === "done" && (
            <>
              {job.total_parsed} adresse(s) lues, {job.new_candidates} nouvelle(s) testée(s),{" "}
              <span className="text-ok">{job.created.length} ajoutée(s)</span>, {job.unreachable}{" "}
              injoignable(s).
            </>
          )}
          {job.status === "error" && <span className="text-critical">Erreur : {job.error}</span>}
        </p>
      )}
      {error && <p className="text-11 text-critical">{error}</p>}
    </div>
  );
}
