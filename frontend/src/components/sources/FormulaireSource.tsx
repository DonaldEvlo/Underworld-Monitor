import { useState } from "react";
import { sourcesApi, type SourceApi, type SourceCreatePayload } from "../../api/sources";
import { sourceTypeLabels } from "../../lib/taxonomy";
import type { SourceType } from "../../types/domain";
import { SOURCE_TYPES, type SourcePrefill } from "./sourcesTypes";

const CHAMP =
  "rounded-lg border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink outline-none transition-colors focus:border-signal/60 disabled:opacity-50";

export function NewSourceForm({
  onCreated,
  prefill,
  ouvertParDefaut = false,
}: {
  onCreated: (source: SourceApi) => void;
  prefill?: SourcePrefill | null;
  ouvertParDefaut?: boolean;
}) {
  const [open, setOpen] = useState(Boolean(prefill?.url) || ouvertParDefaut);
  const [name, setName] = useState(prefill?.name ?? "");
  const [type, setType] = useState<SourceType>(prefill?.url?.includes(".onion") ? "onion" : "forum");
  const [url, setUrl] = useState(prefill?.url ?? "");
  const [requiresJs, setRequiresJs] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const payload: SourceCreatePayload = { name, type, url, requires_js: requiresJs };
      const created = await sourcesApi.create(payload);
      onCreated(created);
      setName("");
      setUrl("");
      setRequiresJs(false);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-[10px] bg-signal px-3.5 py-2 text-13 font-semibold text-on-signal transition-opacity hover:opacity-90"
      >
        Déclarer une source
      </button>
    );
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="flex w-full flex-wrap items-end gap-3 rounded-[14px] border border-signal/25 bg-panel p-4"
    >
      <label className="flex flex-col gap-1">
        <span className="font-caption text-caption text-ink-faint">Nom</span>
        <input required value={name} onChange={(e) => setName(e.target.value)} className={`${CHAMP} font-mono-data`} placeholder="DLS Qilin" />
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-caption text-caption text-ink-faint">Type</span>
        <select value={type} onChange={(e) => setType(e.target.value as SourceType)} className={CHAMP}>
          {SOURCE_TYPES.map((t) => (
            <option key={t} value={t}>
              {sourceTypeLabels[t]}
            </option>
          ))}
        </select>
      </label>
      <label className="flex min-w-64 flex-1 flex-col gap-1">
        <span className="font-caption text-caption text-ink-faint">URL</span>
        <input required value={url} onChange={(e) => setUrl(e.target.value)} className={`${CHAMP} w-full font-mono-data`} placeholder="http://exemple.onion" />
      </label>
      <label
        className="flex items-center gap-2 pb-1.5 text-body-sm text-ink-dim"
        title="Navigateur réel (Playwright) au lieu d'une requête HTTP directe — nécessaire pour les sites à écran d'attente ou défi JS"
      >
        <input type="checkbox" checked={requiresJs} onChange={(e) => setRequiresJs(e.target.checked)} className="accent-signal" />
        Nécessite JS
      </label>
      {error && <p className="w-full text-body-sm text-critical">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={submitting} className="rounded-[10px] bg-signal px-4 py-1.5 text-body-sm font-semibold text-on-signal disabled:opacity-50">
          {submitting ? "Ajout…" : "Ajouter"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="rounded-[10px] border border-line px-4 py-1.5 text-body-sm text-ink-dim hover:text-ink">
          Annuler
        </button>
      </div>
    </form>
  );
}
