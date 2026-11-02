import { useState } from "react";
import { searchApi, type SearchCandidate } from "../api/search";
import { sourcesApi } from "../api/sources";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";

export function Recherche() {
  const [query, setQuery] = useState("");
  const [refinedQuery, setRefinedQuery] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<SearchCandidate[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addedLinks, setAddedLinks] = useState<Set<string>>(new Set());

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    setRefinedQuery(null);
    setCandidates([]);
    try {
      const result = await searchApi.search({ query: query.trim() });
      setRefinedQuery(result.refined_query);
      setCandidates(result.candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSearching(false);
    }
  }

  async function handleAddAsSource(candidate: SearchCandidate) {
    try {
      await sourcesApi.create({ name: candidate.title.slice(0, 80), type: "onion", url: candidate.link });
      setAddedLinks((prev) => new Set(prev).add(candidate.link));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    }
  }

  return (
    <AppLayout title="Recherche" searchPlaceholder="Rechercher sur les moteurs onion...">
      <section className="mb-6 rounded-lg border border-outline-variant bg-surface-container-low p-4">
        <p className="mb-3 text-body-sm text-on-surface-variant">
          Interroge 16 moteurs .onion via Tor ; rien n&apos;est ajouté sans votre choix.
        </p>
        <form onSubmit={(e) => void handleSearch(e)} className="flex flex-wrap items-end gap-3">
          <div className="flex min-w-64 flex-1 flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">Requête</label>
            <input
              required
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={searching}
              className="w-full rounded border border-outline-variant bg-background px-3 py-1.5 font-mono-data text-mono-data outline-none focus:border-primary disabled:opacity-50"
              placeholder="ex: fuite de données bancaires France"
            />
          </div>
          <button
            type="submit"
            disabled={searching || !query.trim()}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-1.5 text-body-sm font-bold text-on-primary transition-all hover:opacity-90 disabled:opacity-50"
          >
            <Icon name="travel_explore" className="text-18" />
            {searching ? "Recherche en cours..." : "Rechercher"}
          </button>
        </form>
        {refinedQuery && !searching && (
          <p className="mt-3 text-body-sm text-on-surface-variant">
            Requête reformulée : <span className="font-mono-data text-primary">{refinedQuery}</span>
          </p>
        )}
      </section>

      {error && (
        <p className="mb-4 rounded border border-error/40 bg-error-container/20 p-3 text-body-sm text-error">
          {error}
        </p>
      )}

      {searching && (
        <div className="rounded-xl border border-outline-variant bg-surface-container p-8 text-center text-on-surface-variant">
          Interrogation des moteurs de recherche onion via Tor (peut prendre jusqu'à une minute)...
        </div>
      )}

      {!searching && candidates.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-outline-variant bg-surface-container">
          <table className="w-full min-w-[720px] border-collapse text-left">
            <thead>
              <tr className="border-b border-outline-variant bg-surface-container-high">
                <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Résultat</th>
                <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Moteur</th>
                <th className="px-4 py-3 text-right font-caption text-caption uppercase text-on-surface-variant">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {candidates.map((candidate) => {
                const added = addedLinks.has(candidate.link);
                return (
                  <tr key={candidate.link} className="transition-colors hover:bg-surface-container-high/50">
                    <td className="px-4 py-4">
                      <div className="flex flex-col">
                        <span className="font-bold text-on-surface">{candidate.title}</span>
                        <span className="font-mono-label text-10 text-on-surface-variant">
                          {candidate.link}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-4 text-body-sm text-on-surface-variant">{candidate.engine}</td>
                    <td className="px-4 py-4 text-right">
                      <button
                        onClick={() => void handleAddAsSource(candidate)}
                        disabled={added}
                        className="rounded border border-primary/30 bg-primary/20 px-3 py-1.5 text-body-sm text-primary transition-all hover:bg-primary/30 disabled:opacity-50"
                      >
                        {added ? "Ajoutée" : "Ajouter comme source"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!searching && refinedQuery && candidates.length === 0 && !error && (
        <div className="rounded-xl border border-outline-variant bg-surface-container p-8 text-center text-on-surface-variant">
          Aucun résultat pertinent trouvé pour cette requête.
        </div>
      )}
    </AppLayout>
  );
}
