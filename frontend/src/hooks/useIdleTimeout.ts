import { useCallback, useEffect, useRef, useState } from "react";

/** Déconnexion automatique après inactivité (réactivée le 2026-10-06). */
export const IDLE_LOGOUT_ENABLED = true;

/** Délai d'inactivité avant déconnexion.
 *
 * ⚠️ Aligné sur `SESSION_IDLE_TIMEOUT_MINUTES` (backend/app/core/config.py) :
 * le serveur révoque une session restée 10 min sans requête (onglet fermé,
 * poste en veille), le navigateur déconnecte après 10 min sans geste de
 * l'utilisateur. Modifier l'un sans l'autre crée un trou ou une déconnexion
 * surprise. */
export const IDLE_TIMEOUT_MS = 10 * 60 * 1000;

/** Délai avant expiration auquel l'avertissement s'affiche. */
export const IDLE_WARNING_MS = 60 * 1000;

/** Signal d'activité envoyé au serveur, au plus une fois par période, tant
 * que l'utilisateur agit. Sans lui, un analyste qui lit un long document sans
 * déclencher d'appel verrait sa session expirer côté serveur. */
const HEARTBEAT_EVERY_MS = 2 * 60 * 1000;

// ⚠️ PARTAGÉS ENTRE ONGLETS. Sans eux, un onglet resté ouvert en arrière-plan
// déconnectait l'utilisateur — et révoquait la session de TOUS ses onglets —
// pendant qu'il travaillait dans un autre.
const CLE_ACTIVITE = "tip_last_activity";
const CLE_SIGNAL = "tip_last_heartbeat";

// Événements considérés comme une activité. `scroll` et `touchstart` couvrent
// la lecture sans clic ni frappe. ⚠️ Les appels API de fond (rafraîchissement
// des compteurs, suivi d'une collecte) n'en font PAS partie : ils ne prouvent
// pas qu'un humain est devant l'écran.
const ACTIVITY_EVENTS = ["mousedown", "mousemove", "keydown", "scroll", "touchstart", "click"] as const;
const ACTIVITY_THROTTLE_MS = 1000;
const TICK_MS = 1000;

// `localStorage` peut LEVER (navigation privée, stockage bloqué) : on retombe
// alors sur l'horloge propre à l'onglet.
function lire(cle: string): number {
  try {
    return Number(localStorage.getItem(cle)) || 0;
  } catch {
    return 0;
  }
}

function ecrire(cle: string, valeur: number): void {
  try {
    localStorage.setItem(cle, String(valeur));
  } catch {
    /* stockage indisponible : l'onglet garde sa propre horloge */
  }
}

interface UseIdleTimeoutOptions {
  /** Actif uniquement quand un utilisateur est connecté. */
  enabled: boolean;
  /** Appelé quand le délai d'inactivité est atteint. */
  onIdle: () => void;
  /** Signal d'activité à transmettre au serveur. */
  onHeartbeat?: () => void;
}

interface UseIdleTimeoutResult {
  /** true pendant la dernière minute avant déconnexion. */
  warning: boolean;
  /** Secondes restantes avant déconnexion (uniquement si `warning`). */
  secondsLeft: number;
  /** Annule l'avertissement et repart pour un cycle complet. */
  stayConnected: () => void;
}

/**
 * Déconnexion automatique après une période sans activité de l'utilisateur.
 *
 * Mesurée sur l'activité la plus récente de TOUS les onglets (horodatage
 * partagé en `localStorage`). La déconnexion elle-même est réelle côté
 * serveur : l'appelant révoque la session (`POST /api/auth/logout`).
 *
 * ⚠️ Les collectes, l'alerting et les tâches planifiées ne dépendent pas de la
 * session : elles continuent dans les workers pendant et après la
 * déconnexion.
 */
export function useIdleTimeout({ enabled, onIdle, onHeartbeat }: UseIdleTimeoutOptions): UseIdleTimeoutResult {
  const [warning, setWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(Math.floor(IDLE_WARNING_MS / 1000));

  const localRef = useRef(0);
  const throttleRef = useRef(0);
  const warningRef = useRef(false);
  const parti = useRef(false);

  // Références stables : les rappels de l'appelant changent à chaque rendu,
  // ce qui ne doit pas reprogrammer la minuterie.
  const onIdleRef = useRef(onIdle);
  const onHeartbeatRef = useRef(onHeartbeat);
  useEffect(() => {
    onIdleRef.current = onIdle;
    onHeartbeatRef.current = onHeartbeat;
  }, [onIdle, onHeartbeat]);

  const noterActivite = useCallback((maintenant: number, signalImmediat = false) => {
    localRef.current = maintenant;
    ecrire(CLE_ACTIVITE, maintenant);
    if (signalImmediat || maintenant - lire(CLE_SIGNAL) >= HEARTBEAT_EVERY_MS) {
      ecrire(CLE_SIGNAL, maintenant);
      onHeartbeatRef.current?.();
    }
  }, []);

  const stayConnected = useCallback(() => {
    warningRef.current = false;
    setWarning(false);
    noterActivite(Date.now(), true);
  }, [noterActivite]);

  useEffect(() => {
    if (!enabled) {
      // Nettoyage à la déconnexion : retirer la modale restée affichée.
      // `enabled` vient du provider, pas d'un état local : pas de boucle.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setWarning(false);
      warningRef.current = false;
      return;
    }
    parti.current = false;
    // La connexion elle-même est une activité.
    noterActivite(Date.now());

    function handleActivity() {
      // Pendant l'avertissement, seul « Rester connecté » prolonge la session :
      // un mouvement de souris ne doit pas l'annuler sans intention claire.
      if (warningRef.current) return;
      const maintenant = Date.now();
      if (maintenant - throttleRef.current < ACTIVITY_THROTTLE_MS) return;
      throttleRef.current = maintenant;
      noterActivite(maintenant);
    }

    function tick() {
      if (parti.current) return;
      const derniere = Math.max(localRef.current, lire(CLE_ACTIVITE));
      const inactif = Date.now() - derniere;
      if (inactif >= IDLE_TIMEOUT_MS) {
        parti.current = true;
        warningRef.current = false;
        setWarning(false);
        onIdleRef.current();
        return;
      }
      const avertir = inactif >= IDLE_TIMEOUT_MS - IDLE_WARNING_MS;
      // Une activité dans un AUTRE onglet fait disparaître l'avertissement ici.
      warningRef.current = avertir;
      setWarning(avertir);
      if (avertir) setSecondsLeft(Math.max(0, Math.ceil((IDLE_TIMEOUT_MS - inactif) / 1000)));
    }

    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, handleActivity, { passive: true });
    }
    const minuterie = window.setInterval(tick, TICK_MS);
    return () => {
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, handleActivity);
      }
      window.clearInterval(minuterie);
    };
  }, [enabled, noterActivite]);

  return { warning, secondsLeft, stayConnected };
}
