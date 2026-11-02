import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/auth-context";
import { GardeRole } from "./GardeRole";

/** Exige une session, puis délègue le périmètre à `GardeRole`.
 *
 * ⚠️ LA GARDE DE RÔLE EST POSÉE ICI, PAS ROUTE PAR ROUTE — même raisonnement
 * que `exige_role` posé sur le routeur et non sur chaque endpoint : une garde
 * oubliée sur une seule route serait un trou qu'aucune vérification de la
 * route voisine ne révèle. Toute route authentifiée passe par ce composant. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center bg-background text-ink-dim">Chargement…</div>;
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <GardeRole>{children}</GardeRole>;
}
