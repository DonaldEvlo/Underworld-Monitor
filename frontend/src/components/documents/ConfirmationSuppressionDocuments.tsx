import { useState } from "react";
import { Icon } from "../ui/Icon";
import { Modale } from "../ui/Modale";

export function DeleteAllConfirmModal({
  total,
  onCancel,
  onConfirm,
}: {
  total: number;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);


  async function handleConfirm() {
    setDeleting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
      setDeleting(false);
    }
  }

  return (
    // Pas de fermeture pendant la suppression : la requête est déjà partie.
    <Modale
      titreId="titre-suppression-documents"
      onFermer={onCancel}
      fermable={!deleting}
      role="alertdialog"
      classeVoile="bg-black/50"
      classePanneau="w-full max-w-md rounded-lg border border-outline-variant bg-surface-container-lowest p-6"
    >
        <div className="mb-3 flex items-center gap-2 text-error">
          <Icon name="warning" className="text-22" />
          <h2 id="titre-suppression-documents" className="font-headline-md text-headline-md">Supprimer tous les documents ?</h2>
        </div>
        <p className="mb-4 text-body-sm text-on-surface-variant">
          Les <strong>{total.toLocaleString("fr-FR")}</strong> documents collectés seront supprimés,{" "}
          <strong>avec toutes leurs détections</strong>. Les sources et la watchlist ne sont pas touchées.
          Cette action est irréversible.
        </p>
        {error && (
          <p className="mb-4 rounded border border-error/40 bg-error-container/20 p-2 text-body-sm text-error">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="rounded border border-outline-variant px-4 py-1.5 text-body-sm transition-all hover:bg-surface-bright disabled:opacity-40"
          >
            Annuler
          </button>
          <button
            onClick={() => void handleConfirm()}
            disabled={deleting}
            className="rounded-lg bg-error px-4 py-1.5 text-body-sm font-bold text-on-error transition-all hover:opacity-90 disabled:opacity-40"
          >
            {deleting ? "Suppression..." : "Supprimer definitivement"}
          </button>
        </div>
    </Modale>
  );
}
