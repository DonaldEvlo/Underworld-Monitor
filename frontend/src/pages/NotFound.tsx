import { Link, useLocation } from "react-router-dom";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";

/**
 * Page introuvable.
 *
 * ⚠️ Sans elle, une URL inconnue rendait un ÉCRAN BLANC — zéro caractère
 * affiché. Un lien partagé entre analystes, ou simplement mal tapé, ne disait
 * rien du tout : ni où l'on est, ni comment revenir.
 */
export function NotFound() {
  const location = useLocation();
  return (
    <AppLayout title="Page introuvable">
      <div className="rounded-lg border border-outline-variant bg-surface-container p-8 text-center">
        <Icon name="explore_off" className="text-40 text-on-surface-variant" />
        <h2 className="mt-3 font-headline-sm text-headline-sm text-on-surface">
          Cette page n&apos;existe pas
        </h2>
        <p className="mt-2 text-body-sm text-on-surface-variant">
          L&apos;adresse{" "}
          <span className="font-mono-data text-on-surface">{location.pathname}</span>{" "}
          ne correspond à aucune page de la plateforme.
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Link
            to="/"
            className="rounded-md bg-primary px-4 py-2 font-mono-data text-12 font-bold text-on-primary transition-opacity hover:opacity-90"
          >
            Retour au tableau de bord
          </Link>
          <Link
            to="/alerts"
            className="rounded-md border border-outline-variant px-4 py-2 font-mono-data text-12 text-on-surface-variant transition-colors hover:bg-surface-bright"
          >
            Voir les alertes
          </Link>
        </div>
      </div>
    </AppLayout>
  );
}
