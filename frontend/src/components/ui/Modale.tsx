import { useEffect, useRef, type ReactNode } from "react";
import { useEscapeKey } from "../../hooks/useEscapeKey";

const FOCALISABLES =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Fenêtre modale accessible : UNE définition pour toutes.
 *
 * ⚠️ Avant (2026-10-01), sur 4 fenêtres modales, une seule se déclarait comme
 * dialogue et AUCUNE ne retenait le focus : la touche Tab partait derrière le
 * voile, dans une page qu'on ne voyait plus, et un lecteur d'écran ne savait
 * pas qu'une fenêtre s'était ouverte. Corriger chaque fenêtre à part aurait
 * produit quatre variantes ; elles divergent toujours.
 *
 * - `role` + `aria-modal` + `aria-labelledby` : la fenêtre s'annonce, avec son
 *   titre ;
 * - le focus entre dans la fenêtre à l'ouverture, Tab y tourne en boucle, et il
 *   revient à l'élément d'origine à la fermeture ;
 * - Échap et le clic sur le voile ferment, sauf si `fermable` est faux (une
 *   suppression en cours ne doit pas laisser croire à une annulation).
 */
export function Modale({
  titreId,
  onFermer,
  fermable = true,
  role = "dialog",
  position = "centre",
  classeVoile = "bg-black/60",
  classePanneau,
  zIndex = "z-50",
  children,
}: {
  titreId: string;
  onFermer: () => void;
  fermable?: boolean;
  role?: "dialog" | "alertdialog";
  position?: "centre" | "droite";
  classeVoile?: string;
  classePanneau: string;
  zIndex?: string;
  children: ReactNode;
}) {
  const panneau = useRef<HTMLDivElement>(null);
  // Mémorisé au RENDU, pas dans l'effet : un bouton `autoFocus` de la fenêtre
  // prend le focus avant que l'effet ne s'exécute, l'origine serait perdue.
  const origine = useRef<Element | null>(document.activeElement);

  useEscapeKey(fermable, onFermer);

  useEffect(() => {
    const racine = panneau.current;
    const elementOrigine = origine.current;
    // Un `autoFocus` posé par la fenêtre elle-même l'emporte (« Rester
    // connecté » plutôt que « Se déconnecter »).
    if (racine && !racine.contains(document.activeElement)) {
      const premier = racine.querySelector<HTMLElement>(FOCALISABLES);
      (premier ?? racine).focus();
    }
    function retenir(event: KeyboardEvent) {
      if (event.key !== "Tab" || !racine) return;
      const elements = Array.from(racine.querySelectorAll<HTMLElement>(FOCALISABLES));
      if (elements.length === 0) {
        event.preventDefault();
        return;
      }
      const premier = elements[0];
      const dernier = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === premier) {
        event.preventDefault();
        dernier.focus();
      } else if (!event.shiftKey && document.activeElement === dernier) {
        event.preventDefault();
        premier.focus();
      }
    }
    document.addEventListener("keydown", retenir);
    return () => {
      document.removeEventListener("keydown", retenir);
      // Rendre le focus là où il était : sinon il retombe en haut de la page
      // et l'utilisateur au clavier perd sa place.
      if (elementOrigine instanceof HTMLElement) elementOrigine.focus();
    };
  }, []);

  return (
    <div
      className={`fixed inset-0 ${zIndex} flex ${
        position === "droite" ? "justify-end" : "items-center justify-center"
      } ${classeVoile}`}
      onClick={fermable ? onFermer : undefined}
    >
      <div
        ref={panneau}
        role={role}
        aria-modal="true"
        aria-labelledby={titreId}
        tabIndex={-1}
        className={`outline-none ${classePanneau}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
