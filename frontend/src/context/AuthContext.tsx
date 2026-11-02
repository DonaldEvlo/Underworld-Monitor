import { useCallback, useEffect, useState, type ReactNode } from "react";
import { authApi, type UserApi } from "../api/auth";
import { AuthContext, setLogoutReason } from "./auth-context";
import { registerSessionExpiredHandler } from "../api/client";
import { ACCESS_KEY, tokenStorage } from "../api/tokenStorage";
import { IdleWarningModal } from "../components/auth/IdleWarningModal";
import { IDLE_LOGOUT_ENABLED, IDLE_TIMEOUT_MS, useIdleTimeout } from "../hooks/useIdleTimeout";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserApi | null>(null);
  // Sans token en storage il n'y a aucun appel /me a attendre : l'etat est
  // connu des l'initialisation. Le deduire ici plutot que de le corriger dans
  // un effet evite un rendu "Chargement..." inutile pour un visiteur non
  // connecte (RequireAuth affiche cet ecran tant que loading est vrai).
  const [loading, setLoading] = useState(() => tokenStorage.getAccessToken() !== null);

  /** Déconnexion RÉELLE : la session est révoquée côté serveur (ses jetons ne
   * servent plus, sur aucun onglet), puis les jetons locaux sont effacés.
   *
   * ⚠️ L'appel serveur part AVANT l'effacement (il lit le jeton au départ) et
   * n'est pas attendu : un serveur injoignable ne doit pas empêcher de quitter
   * l'interface — la session expirera de toute façon côté serveur après
   * 10 min sans requête. Sans jeton, aucun appel : pas de boucle possible. */
  const terminer = useCallback((motif: "logout" | "idle") => {
    if (tokenStorage.getAccessToken()) {
      void authApi.logout(motif).catch(() => undefined);
    }
    tokenStorage.clear();
    setUser(null);
  }, []);

  const logout = useCallback(() => terminer("logout"), [terminer]);

  const logoutForInactivity = useCallback(() => {
    setLogoutReason(
      `Vous avez été déconnecté après ${IDLE_TIMEOUT_MS / 60000} minutes d'inactivité. ` +
        "Les collectes et les tâches planifiées ont continué de tourner.",
    );
    terminer("idle");
  }, [terminer]);

  const heartbeat = useCallback(() => {
    void authApi.heartbeat().catch(() => undefined);
  }, []);

  const { warning, secondsLeft, stayConnected } = useIdleTimeout({
    enabled: IDLE_LOGOUT_ENABLED && user !== null,
    onIdle: logoutForInactivity,
    onHeartbeat: heartbeat,
  });

  // Session révoquée côté serveur (refresh refusé) : on quitte l'interface
  // sans rappeler /logout.
  useEffect(() => {
    registerSessionExpiredHandler(() => {
      tokenStorage.clear();
      setUser(null);
    });
  }, []);

  // ⚠️ DÉCONNEXION D'UN AUTRE ONGLET : les jetons sont partagés
  // (localStorage). Quand un onglet les efface, les autres doivent quitter
  // l'interface aussitôt plutôt qu'au prochain appel refusé.
  useEffect(() => {
    function surStockage(e: StorageEvent) {
      if (e.key === ACCESS_KEY && e.newValue === null) {
        setUser((courant) => {
          if (courant) setLogoutReason("Vous avez été déconnecté (session fermée dans un autre onglet).");
          return null;
        });
      }
    }
    window.addEventListener("storage", surStockage);
    return () => window.removeEventListener("storage", surStockage);
  }, []);

  useEffect(() => {
    if (!tokenStorage.getAccessToken()) return;
    authApi
      .me()
      .then(setUser)
      .catch(() => {
        // Jeton refusé et refresh impossible (session révoquée ou expirée) :
        // client.ts a déjà vidé le stockage. Rien à refaire ici.
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    const tokens = await authApi.login(username, password);
    tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);
    const me = await authApi.me();
    setUser(me);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
      {warning && user && (
        <IdleWarningModal secondsLeft={secondsLeft} onStayConnected={stayConnected} onLogout={logoutForInactivity} />
      )}
    </AuthContext.Provider>
  );
}
