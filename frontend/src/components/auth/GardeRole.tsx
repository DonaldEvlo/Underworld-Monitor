import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/auth-context";
import { NotFound } from "../../pages/NotFound";
import { AccesRefuse } from "../../pages/AccesRefuse";
import { peutAcceder, perimetreDeRoute, routeAccueil } from "../../lib/roles";

/**
 * Garde de périmètre sur la route courante.
 *
 * ⚠️ AVANT CE COMPOSANT, LES ROUTES N'ÉTAIENT PAS GARDÉES DU TOUT. Seul le
 * menu était filtré : un analyste qui tapait `/comptes`, ou un RSSI qui tapait
 * `/documents`, ouvrait la page et voyait chacun de ses appels répondre 403.
 * L'écran affichait une erreur technique là où il fallait une phrase — et le
 * commentaire du code appelait cela « le comportement attendu ». Ce n'en était
 * pas un : une interface qui ouvre une page pour la remplir de refus est
 * exactement ce que la doctrine du menu interdit.
 *
 * ⚠️ CE N'EST PAS DE LA SÉCURITÉ. La garde qui compte reste serveur
 * (`api/deps.exige_role`, 403). Celle-ci sert à dire POURQUOI, tout de suite,
 * plutôt qu'à laisser l'utilisateur déduire un droit manquant d'une cascade
 * d'erreurs.
 *
 * ⚠️ UNE ROUTE NON DÉCLARÉE REND « PAGE INTROUVABLE », PAS LA PAGE. C'est le
 * défaut sûr : une route ajoutée à `App.tsx` sans être déclarée dans
 * `lib/roles.ts` échoue bruyamment et se corrige, au lieu de s'ouvrir en
 * silence à tous les rôles. Les URL réellement inconnues aboutissent au même
 * écran, qui est celui qu'elles doivent avoir.
 */
export function GardeRole({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  const perimetre = perimetreDeRoute(location.pathname);

  if (perimetre === undefined) return <NotFound />;

  if (!peutAcceder(user?.role, perimetre)) {
    // ⚠️ LA RACINE REDIRIGE, ELLE NE REFUSE PAS. C'est la page d'atterrissage
    // après connexion : y afficher un refus ferait accueillir le RSSI par un
    // mur dès sa première seconde dans l'outil. Partout ailleurs le refus est
    // explicite — il répond à une navigation délibérée.
    const accueil = routeAccueil(user?.role);
    if (location.pathname === "/" && accueil !== "/") {
      return <Navigate to={accueil} replace />;
    }
    return <AccesRefuse perimetre={perimetre} />;
  }

  return <>{children}</>;
}
