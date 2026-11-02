/** Contexte d'authentification et utilitaires associes.
 *
 * Separe de AuthContext.tsx (qui n'exporte plus que le composant AuthProvider)
 * pour que le Fast Refresh de Vite fonctionne : un fichier melangeant
 * composants et exports non-composants force un rechargement complet a chaque
 * edition au lieu d'un remplacement a chaud (regle react-refresh). */

import { createContext, useContext } from "react";
import type { UserApi } from "../api/auth";

export interface AuthContextValue {
  user: UserApi | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth doit être utilisé à l'intérieur d'un AuthProvider");
  return ctx;
}

/** Motif de la derniere deconnexion, lu par la page de login pour expliquer a
 * l'utilisateur pourquoi il s'y retrouve. Stocke en sessionStorage plutot que
 * dans le state React : la redirection vers /login remonte l'arbre et
 * reinitialise le contexte. */
const LOGOUT_REASON_KEY = "tip_logout_reason";

export function setLogoutReason(reason: string): void {
  sessionStorage.setItem(LOGOUT_REASON_KEY, reason);
}

/** ⚠️ LECTURE et EFFACEMENT séparés. Lu et effacé d'un coup dans un
 * initialiseur `useState`, le motif disparaissait en développement : le mode
 * strict de React appelle l'initialiseur DEUX fois, la seconde trouvait le
 * stockage déjà vidé (constaté au test de la déconnexion le 2026-10-06). */
export function readLogoutReason(): string | null {
  try {
    return sessionStorage.getItem(LOGOUT_REASON_KEY);
  } catch {
    return null;
  }
}

export function clearLogoutReason(): void {
  try {
    sessionStorage.removeItem(LOGOUT_REASON_KEY);
  } catch {
    /* stockage indisponible */
  }
}
