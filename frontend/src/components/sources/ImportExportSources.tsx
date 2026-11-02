import { useRef, useState } from "react";
import { sourcesApi, type SourceExportEnvelope, type SourceImportResult } from "../../api/sources";

export function ImportExportControls({ onImported }: { onImported: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [messageIsError, setMessageIsError] = useState(false);

  async function handleExport() {
    try {
      const envelope = await sourcesApi.exportAll();
      const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `sources_export_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMessageIsError(true);
      setMessage(err instanceof Error ? err.message : "Échec de l'export");
    }
  }

  async function handleFileSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // permet de re-sélectionner le même fichier ensuite
    if (!file) return;
    setImporting(true);
    setMessage(null);
    try {
      const envelope = JSON.parse(await file.text()) as SourceExportEnvelope;
      const result: SourceImportResult = await sourcesApi.importAll(envelope);
      setMessageIsError(result.errors.length > 0);
      setMessage(
        `${result.created} source(s) importée(s), ${result.skipped} déjà présente(s) ignorée(s)` +
          (result.errors.length > 0 ? `, ${result.errors.length} erreur(s)` : "."),
      );
      onImported();
    } catch (err) {
      setMessageIsError(true);
      setMessage(err instanceof Error ? err.message : "Fichier d'import invalide");
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex gap-2">
        <button onClick={() => void handleExport()} className="flex-1 rounded-[10px] border border-line bg-panel-sunken px-3 py-2 text-body-sm text-ink transition-colors hover:border-signal/35" title="Télécharger toutes les sources au format JSON">
          Exporter le catalogue
        </button>
        <button onClick={() => fileInputRef.current?.click()} disabled={importing} className="flex-1 rounded-[10px] border border-line bg-panel-sunken px-3 py-2 text-body-sm text-ink transition-colors hover:border-signal/35 disabled:opacity-50" title="Importer des sources depuis un export JSON">
          {importing ? "Import…" : "Importer un JSON"}
        </button>
        <input ref={fileInputRef} type="file" accept="application/json" hidden onChange={(e) => void handleFileSelected(e)} />
      </div>
      {message && <p className={`text-11 ${messageIsError ? "text-critical" : "text-ink-dim"}`}>{message}</p>}
    </div>
  );
}
