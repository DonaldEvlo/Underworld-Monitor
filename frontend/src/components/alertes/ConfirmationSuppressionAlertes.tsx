import { useState } from "react";
import { Icon } from "../ui/Icon";
import { Modale } from "../ui/Modale";

export function DeleteAllAlertsConfirmModal({
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
    // Pas de fermeture pendant la suppression : Échap ou le voile ne doivent
    // pas laisser croire à une annulation alors que la requête est partie.
    <Modale
      titreId="titre-suppression-alertes"
      onFermer={onCancel}
      fermable={!deleting}
      role="alertdialog"
      classePanneau="w-full max-w-md rounded-[18px] border border-line bg-panel p-6"
    >
        <div className="mb-3 flex items-center gap-2 text-critical">
          <Icon name="warning" className="text-22" />
          <h2 id="titre-suppression-alertes" className="font-display text-headline-md">Supprimer toutes les alertes ?</h2>
        </div>
        <p className="mb-4 text-body-sm text-ink-dim">
          Les <strong className="text-ink">{total.toLocaleString("fr-FR")}</strong> alerte(s) en base
          seront supprimées (statut, résumé, rattachements). Détections, documents et organisations
          ne sont pas touchés.{" "}
          <strong className="text-ink">
            Une régénération ne recrée que les alertes des 7 derniers jours
          </strong>{" "}
          : les incidents plus anciens sont hors de la fenêtre et ne reviendront pas.
        </p>
        {error && (
          <p className="mb-4 rounded border border-critical/40 bg-critical/10 p-2 text-body-sm text-critical">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="rounded-[10px] border border-line px-4 py-1.5 text-body-sm text-ink transition-colors hover:bg-panel-raised disabled:opacity-40"
          >
            Annuler
          </button>
          <button
            onClick={() => void handleConfirm()}
            disabled={deleting}
            className="rounded-[10px] bg-critical px-4 py-1.5 text-body-sm font-bold text-on-error transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {deleting ? "Suppression…" : "Supprimer définitivement"}
          </button>
        </div>
    </Modale>
  );
}
