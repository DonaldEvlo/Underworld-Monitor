import { useState } from "react";
import { downloadFile } from "../../api/client";
import { Icon } from "./Icon";

/**
 * Faire SORTIR ce que l'analyste voit.
 *
 * ⚠️ Aucun export n'existait nulle part : pour transmettre un dossier à une
 * victime ou l'archiver, il fallait des captures d'écran.
 */
export function BoutonExport({
  chemin,
  nom,
  libelle = "Exporter en CSV",
  titre = "Télécharger au format CSV (séparateur ; lisible par Excel)",
}: {
  chemin: string;
  nom: string;
  libelle?: string;
  titre?: string;
}) {
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  return (
    <span className="inline-flex flex-col">
      <button
        onClick={() => {
          setOccupe(true);
          setErreur(null);
          downloadFile(chemin, nom)
            .catch((err) =>
              setErreur(err instanceof Error ? err.message : "Export impossible"),
            )
            .finally(() => setOccupe(false));
        }}
        disabled={occupe}
        title={titre}
        className="flex items-center gap-1 rounded-md border border-outline-variant px-2 py-1 font-mono-data text-11 text-on-surface-variant transition-colors hover:bg-surface-bright hover:text-on-surface disabled:opacity-40"
      >
        <Icon
          name={occupe ? "progress_activity" : "download"}
          className={`text-14 ${occupe ? "animate-spin" : ""}`}
        />
        {libelle}
      </button>
      {erreur && <span className="mt-0.5 text-10 text-error">{erreur}</span>}
    </span>
  );
}
