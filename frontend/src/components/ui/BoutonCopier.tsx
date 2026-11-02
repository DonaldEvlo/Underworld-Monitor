import { useEffect, useState } from "react";
import { Icon } from "./Icon";

/** Copie une valeur dans le presse-papiers et le confirme à l'écran.
 *
 * Usage principal : une adresse `.onion`, affichée sans lien (elle ne mène
 * nulle part depuis un navigateur ordinaire), que l'analyste colle ensuite
 * dans Tor Browser pour vérifier la source.
 *
 * ⚠️ `navigator.clipboard` n'existe que dans un contexte sécurisé (HTTPS ou
 * localhost) : ouverte par une adresse IP en HTTP, l'interface n'y a pas
 * accès. Repli sur une zone de texte temporaire, puis échec AFFICHÉ — un clic
 * sans effet ni message se lirait comme une copie réussie.
 */
export function BoutonCopier({ valeur, libelle = "Copier" }: { valeur: string; libelle?: string }) {
  const [etat, setEtat] = useState<"repos" | "copie" | "echec">("repos");

  useEffect(() => {
    if (etat === "repos") return;
    const minuterie = window.setTimeout(() => setEtat("repos"), 2000);
    return () => window.clearTimeout(minuterie);
  }, [etat]);

  async function copier() {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(valeur);
      } else if (!copierParZoneDeTexte(valeur)) {
        throw new Error("presse-papiers indisponible");
      }
      setEtat("copie");
    } catch {
      setEtat("echec");
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copier()}
      aria-label={`${libelle} : ${valeur}`}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-line px-2 py-1 font-mono-label text-10.5 text-ink-dim transition-colors hover:border-signal/40 hover:text-ink"
    >
      <Icon name={etat === "copie" ? "check" : "content_copy"} className="text-14" />
      <span aria-live="polite">
        {etat === "copie" ? "Copiée" : etat === "echec" ? "Copie impossible" : libelle}
      </span>
    </button>
  );
}

function copierParZoneDeTexte(valeur: string): boolean {
  const zone = document.createElement("textarea");
  zone.value = valeur;
  zone.setAttribute("readonly", "");
  zone.style.position = "fixed";
  zone.style.opacity = "0";
  document.body.appendChild(zone);
  zone.select();
  try {
    // API dépréciée, mais seule voie hors contexte sécurisé.
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(zone);
  }
}
