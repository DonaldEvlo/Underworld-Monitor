import { useSyncExternalStore } from "react";

/**
 * Mode réduit de la barre latérale (icônes seules).
 *
 * ⚠️ ÉTAT HORS DES COMPOSANTS, À DESSEIN — pour deux raisons distinctes.
 *
 * 1. **Chaque page rend son propre `AppLayout`**, donc la barre latérale est
 *    recréée à chaque navigation (c'est déjà ce qui obligeait à conserver la
 *    position de défilement du menu hors du composant, voir `Sidebar.tsx`).
 *    Un `useState` local serait remis à « déployée » à chaque clic.
 * 2. **`AppLayout` et `Sidebar` lisent le MÊME état** : la première décale son
 *    contenu de la largeur de la seconde. Les laisser diverger afficherait une
 *    bande vide ou, pire, un menu recouvrant la page.
 *
 * Même patron que `useTestSources` : module + `useSyncExternalStore`.
 *
 * ⚠️ Le choix est PERSISTÉ. Réduire la barre est une préférence de poste de
 * travail (écran 13", projection) : la redemander à chaque
 * session en ferait une gêne plutôt qu'un réglage.
 */

const CLE = "sidebar_reduite";

/**
 * ⚠️ `localStorage` peut LEVER, pas seulement rendre `null` : navigation
 * privée, stockage de site bloqué. Une préférence d'affichage ne doit jamais
 * empêcher l'application de démarrer — on retombe silencieusement sur
 * « déployée », qui est le comportement historique.
 */
function lireStockage(): boolean {
  try {
    return localStorage.getItem(CLE) === "1";
  } catch {
    return false;
  }
}

function ecrireStockage(valeur: boolean): void {
  try {
    localStorage.setItem(CLE, valeur ? "1" : "0");
  } catch {
    // Préférence non conservée : sans conséquence sur la session en cours.
  }
}

let reduite = lireStockage();
const abonnes = new Set<() => void>();

function sabonner(f: () => void): () => void {
  abonnes.add(f);
  return () => abonnes.delete(f);
}

function lire(): boolean {
  return reduite;
}

export function basculerSidebarReduite(): void {
  reduite = !reduite;
  ecrireStockage(reduite);
  for (const f of abonnes) f();
}

/** `true` quand la barre est en mode icônes seules. */
export function useSidebarReduite(): boolean {
  return useSyncExternalStore(sabonner, lire, lire);
}
