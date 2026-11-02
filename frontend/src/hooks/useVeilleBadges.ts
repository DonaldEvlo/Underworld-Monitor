import { useEffect, useState } from "react";
import { activityApi, type ActivityApi } from "../api/activity";

/** Compteurs affiches en pastille dans la barre laterale.
 *
 * ⚠️ CACHE DE MODULE, ET C'EST LE POINT DE CETTE COUCHE. La barre laterale est
 * remontee a CHAQUE navigation : ce n'est pas un gabarit partage, chaque page
 * rend son propre `AppLayout`. Sans cache, ouvrir cinq pages declencherait cinq
 * appels a `/api/stats/activity` — et le tableau de bord, qui interroge deja la
 * meme route pour son bandeau, la demanderait deux fois par affichage.
 */
const DUREE_CACHE_MS = 60_000;

let cache: { valeur: ActivityApi; expire: number } | null = null;
let enVol: Promise<ActivityApi> | null = null;

function charger(): Promise<ActivityApi> {
  const maintenant = Date.now();
  if (cache && cache.expire > maintenant) {
    return Promise.resolve(cache.valeur);
  }
  // Une seule requete en vol : deux composants montes dans le meme rendu
  // (barre laterale + bandeau du tableau de bord) partagent la meme promesse.
  enVol ??= activityApi
    .get()
    .then((valeur) => {
      cache = { valeur, expire: Date.now() + DUREE_CACHE_MS };
      return valeur;
    })
    .finally(() => {
      enVol = null;
    });
  return enVol;
}

/** Invalide le cache — a appeler apres une action qui change les compteurs
 * (generation d'alertes, ajout d'un selecteur, collecte). */
export function invaliderBadges(): void {
  cache = null;
}

export function useVeilleBadges(): ActivityApi | null {
  const [activite, setActivite] = useState<ActivityApi | null>(() => cache?.valeur ?? null);

  useEffect(() => {
    let vivant = true;
    charger().then(
      (valeur) => {
        if (vivant) setActivite(valeur);
      },
      () => {
        // ⚠️ Un compteur indisponible ne doit RIEN casser : la pastille
        // disparait, la navigation reste utilisable. C'est la seule erreur du
        // projet qu'on avale volontairement, parce que l'echec est visible
        // (pas de pastille) et sans consequence sur le livrable.
      },
    );
    return () => {
      vivant = false;
    };
  }, []);

  return activite;
}
