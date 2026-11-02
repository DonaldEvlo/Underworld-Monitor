import { useState } from "react";
import { sourcesApi, type SourceApi } from "../../api/sources";
import { Icon } from "../ui/Icon";
import { sourceTypeLabels } from "../../lib/taxonomy";
import type { SourceType } from "../../types/domain";
import { dateHeure } from "../../lib/format";
import { SOURCE_TYPES } from "./sourcesTypes";

const CHAMP =
  "rounded-lg border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink outline-none transition-colors focus:border-signal/60 disabled:opacity-50";

export function EditSourceRow({
  source,
  onSaved,
  onCancel,
}: {
  source: SourceApi;
  onSaved: (source: SourceApi) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(source.name);
  const [type, setType] = useState<SourceType>(source.type);
  const [url, setUrl] = useState(source.url);
  const [active, setActive] = useState(source.active);
  const [requiresJs, setRequiresJs] = useState(source.requires_js);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (!name.trim() || !url.trim()) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await sourcesApi.update(source.id, {
          name: name.trim(),
          type,
          url: url.trim(),
          active,
          requires_js: requiresJs,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSaving(false);
    }
  }

  return (
    <tr className="bg-panel-raised/40">
      <td className="px-4 py-3">
        <div className="flex flex-col gap-1">
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} disabled={saving} className={`${CHAMP} font-semibold`} placeholder="Nom" />
          <input value={url} onChange={(e) => setUrl(e.target.value)} disabled={saving} className={`${CHAMP} font-mono-data text-11`} placeholder="URL" />
        </div>
        {error && <p className="mt-1 text-11 text-critical">{error}</p>}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-col gap-1.5">
          <select value={type} onChange={(e) => setType(e.target.value as SourceType)} disabled={saving} className={CHAMP}>
            {SOURCE_TYPES.map((t) => (
              <option key={t} value={t}>
                {sourceTypeLabels[t]}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-body-sm text-ink-dim">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} disabled={saving} className="accent-signal" />
            Active
          </label>
          <label className="flex items-center gap-2 text-body-sm text-ink-dim">
            <input type="checkbox" checked={requiresJs} onChange={(e) => setRequiresJs(e.target.checked)} disabled={saving} className="accent-signal" />
            Nécessite JS
          </label>
        </div>
      </td>
      <td className="px-4 py-3 font-mono-data text-11 text-ink-dim">
        {dateHeure(source.last_collected_at, "jamais")}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex justify-end gap-1">
          <button onClick={() => void handleSave()} disabled={saving || !name.trim() || !url.trim()} className="rounded-md p-1.5 text-signal hover:bg-signal/15 disabled:opacity-50" title="Enregistrer">
            <Icon name="check" className="text-16" />
          </button>
          <button onClick={onCancel} disabled={saving} className="rounded-md p-1.5 text-ink-dim hover:bg-panel-raised" title="Annuler">
            <Icon name="close" className="text-16" />
          </button>
        </div>
      </td>
    </tr>
  );
}
