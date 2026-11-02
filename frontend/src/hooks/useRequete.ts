import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

type Cle = string | number | boolean | null | undefined;

interface Etat<T> {
  cle: string | null;
  donnees: T | null;
  erreur: string | null;
}

/** Chargement de données d'une page : UNE implémentation pour toutes.
 *
 * ⚠️ Avant (2026-10-01), chaque page réécrivait `useEffect` + `useState` +
 * `try/catch`, et plusieurs n'ignoraient pas les réponses PÉRIMÉES : changer
 * deux fois de filtre sur Détections lançait deux requêtes, et si la première
 * revenait en dernier, la liste affichée ne correspondait plus au filtre
 * affiché. Rien ne le signalait.
 *
 * - `deps` : valeurs primitives (filtres, identifiant). Leur changement relance
 *   la requête ; seule la réponse de la DERNIÈRE requête est retenue.
 * - `chargement` est DÉRIVÉ (la réponse retenue correspond-elle aux filtres
 *   courants ?) plutôt que posé dans l'effet : pas de rendu en cascade.
 * - `garderPendantChargement` (vrai par défaut) laisse la liste précédente à
 *   l'écran pendant un rechargement. Faux pour un panneau de détail : afficher
 *   l'ancien document sous le titre du nouveau serait trompeur.
 * - `actif` à faux suspend la requête (périmètre de rôle, saisie vide).
 */
export function useRequete<T>(
  charger: () => Promise<T>,
  deps: readonly Cle[],
  options: { actif?: boolean; garderPendantChargement?: boolean } = {},
) {
  const { actif = true, garderPendantChargement = true } = options;
  const [tick, setTick] = useState(0);
  const cle = JSON.stringify([...deps, tick]);
  const [etat, setEtat] = useState<Etat<T>>({ cle: null, donnees: null, erreur: null });
  // La fonction de chargement change à chaque rendu (fermeture sur les
  // filtres) : on lit toujours la plus récente, sans en faire une dépendance.
  const chargerRef = useRef(charger);
  // Mise à jour AVANT l'effet de chargement (les effets de mise en page
  // passent d'abord) ; écrire une ref pendant le rendu est interdit.
  useLayoutEffect(() => {
    chargerRef.current = charger;
  });
  const derniere = useRef<string | null>(null);

  useEffect(() => {
    if (!actif) return;
    derniere.current = cle;
    chargerRef
      .current()
      .then((donnees) => {
        if (derniere.current === cle) setEtat({ cle, donnees, erreur: null });
      })
      .catch((err: unknown) => {
        if (derniere.current !== cle) return;
        setEtat((precedent) => ({
          cle,
          donnees: precedent.donnees,
          erreur: err instanceof Error ? err.message : "Erreur inconnue",
        }));
      });
  }, [cle, actif]);

  const recharger = useCallback(() => setTick((t) => t + 1), []);
  /** Mise à jour locale après une action (suppression, bascule) sans
   * recharger toute la liste. */
  const modifier = useCallback(
    (fn: (precedent: T | null) => T | null) =>
      setEtat((e) => ({ ...e, donnees: fn(e.donnees) })),
    [],
  );

  const aJour = etat.cle === cle;
  return {
    donnees: aJour || garderPendantChargement ? etat.donnees : null,
    erreur: aJour ? etat.erreur : null,
    chargement: actif && !aJour,
    recharger,
    modifier,
  };
}
