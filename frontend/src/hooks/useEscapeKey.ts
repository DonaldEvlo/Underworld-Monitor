import { useEffect } from "react";

/** Appelle `onEscape` quand la touche Échap est pressée, tant que `active` est
 * vrai.
 *
 * Toute surface modale doit être refermable au clavier : un utilisateur qui ne
 * peut pas viser le voile à la souris (ou qui navigue au clavier) se retrouve
 * sinon piégé dans le dialogue. Regroupé ici plutôt que dupliqué dans chaque
 * modale, pour que le comportement reste identique partout. */
export function useEscapeKey(active: boolean, onEscape: () => void) {
  useEffect(() => {
    if (!active) return;
    function handle(event: KeyboardEvent) {
      if (event.key === "Escape") onEscape();
    }
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [active, onEscape]);
}
