import { IDLE_TIMEOUT_MS, IDLE_WARNING_MS } from "../../hooks/useIdleTimeout";
import { Icon } from "../ui/Icon";
import { Modale } from "../ui/Modale";

/**
 * Avertissement affiche pendant la derniere minute avant deconnexion pour
 * inactivite (voir hooks/useIdleTimeout.ts). Volontairement non fermable au
 * clic sur l'overlay : c'est un choix explicite entre "rester connecte" et
 * "se deconnecter maintenant", pas une notification a ignorer d'un clic
 * distrait.
 */
export function IdleWarningModal({
  secondsLeft,
  onStayConnected,
  onLogout,
}: {
  secondsLeft: number;
  onStayConnected: () => void;
  onLogout: () => void;
}) {
  return (
    // Non fermable (voile, Échap) : c'est un choix explicite, pas une
    // notification à écarter d'un geste distrait.
    <Modale
      titreId="idle-warning-title"
      onFermer={onStayConnected}
      fermable={false}
      role="alertdialog"
      zIndex="z-[60]"
      classePanneau="w-full max-w-md rounded-lg border border-warn/40 bg-surface-container-lowest p-6"
    >
        <div className="mb-3 flex items-center gap-2 text-warn">
          <Icon name="timer" className="text-22" />
          <h2 id="idle-warning-title" className="font-headline-md text-headline-md">
            Session bientôt expirée
          </h2>
        </div>

        <p className="mb-4 text-body-sm text-on-surface-variant">
          Aucune activité détectée depuis{" "}
          {Math.round((IDLE_TIMEOUT_MS - IDLE_WARNING_MS) / 60000)} minutes. Vous serez
          déconnecté automatiquement dans{" "}
          <strong className="font-mono-data text-on-surface">{secondsLeft}s</strong>{" "}
          pour protéger l&apos;accès aux alertes depuis ce poste.
        </p>
        <p className="mb-4 text-body-sm text-on-surface-variant">
          Les collectes et les tâches planifiées continuent de tourner, que vous
          restiez connecté ou non.
        </p>

        <div className="flex justify-end gap-3">
          <button
            onClick={onLogout}
            className="rounded border border-outline-variant px-4 py-1.5 text-body-sm transition-all hover:bg-surface-bright"
          >
            Se déconnecter
          </button>
          <button
            onClick={onStayConnected}
            autoFocus
            className="rounded-lg bg-primary px-4 py-1.5 text-body-sm font-bold text-on-primary transition-all hover:opacity-90"
          >
            Rester connecté
          </button>
        </div>
    </Modale>
  );
}
