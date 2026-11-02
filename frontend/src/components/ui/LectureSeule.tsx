import { Icon } from "./Icon";

/**
 * Mention « lecture seule », posée là où des contrôles ont été retirés parce
 * que le rôle ne les a pas.
 *
 * ⚠️ POURQUOI UNE MENTION PLUTÔT QUE RIEN. Masquer un bouton sans rien dire
 * laisse l'utilisateur chercher une fonctionnalité qu'il croit cassée ou
 * disparue : c'est exactement ce qui rendait les compteurs d'alerte
 * incompréhensibles avant qu'on affiche leur périmètre. Une page amputée en
 * silence se lit comme une panne.
 *
 * ⚠️ POURQUOI PAS UN CONTRÔLE DÉSACTIVÉ. Un bouton grisé promet le geste puis
 * le refuse — même défaut que la barre de recherche visible mais inerte sur
 * trois pages. On retire le contrôle et on dit pourquoi.
 */
export function LectureSeule({ quoi }: { quoi: string }) {
  return (
    <p className="mb-4 flex items-start gap-2 rounded border border-line bg-panel-raised/60 p-3 text-body-sm text-ink-dim">
      <Icon name="lock" className="mt-0.5 shrink-0 text-16 text-ink-faint" />
      <span>
        Lecture seule — {quoi} est réservé à l&apos;administrateur. Les données
        restent consultables.
      </span>
    </p>
  );
}
