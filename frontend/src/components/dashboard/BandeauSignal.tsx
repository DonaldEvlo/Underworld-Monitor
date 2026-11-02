import { schedulesApi, type ScheduleApi } from "../../api/schedules";
import type { SourceApi } from "../../api/sources";
import { dateHeureCourte } from "../../lib/format";
import { useRequete } from "../../hooks/useRequete";

interface BandeauSignalProps {
  sources: SourceApi[];
  /** Vient de `/api/stats/activity` : `SourceApi` ne porte pas le statut de la
   * derniere collecte, seulement sa date. */
  sourcesEnEchec: number;
}


/** Bandeau d'etat : la machine tient en UNE ligne.
 *
 * ⚠️ La volumetrie apparaissait TROIS FOIS sur le meme ecran (bandeau heros,
 * trois cartes, puis une ligne de texte). Elle situe la machine, elle n'est
 * pas le travail : elle descend ici, sur une seule bande, et la hauteur
 * recuperee sert a ce qu'il y a a traiter.
 */
export function BandeauSignal({ sources, sourcesEnEchec }: BandeauSignalProps) {
  // Le bandeau reste utile sans le prochain passage : un échec n'affiche rien.
  const requete = useRequete(async () => (await schedulesApi.list()).schedules, []);
  const taches: ScheduleApi[] = requete.donnees ?? [];

  const actives = sources.filter((s) => s.active);
  // Les dates ISO se comparent comme des chaines : la plus grande est la plus
  // recente. (`.at(-1)` n'est pas disponible : la cible TypeScript du projet
  // est anterieure a ES2022.)
  const horodatages = actives
    .map((s) => s.last_collected_at)
    .filter((d): d is string => Boolean(d))
    .sort();
  const derniere = horodatages.length > 0 ? horodatages[horodatages.length - 1] : null;

  // ⚠️ Ne retient QUE les entrees actives : une planification suspendue ne
  // declenchera rien, l'annoncer comme « prochain passage » serait faux.
  const planifiees = taches.filter((t) => t.enabled);

  return (
    <div className="pulse-panel pulse-panel-live relative mb-4 flex flex-wrap items-center gap-x-7 gap-y-3 overflow-hidden px-5 py-3">
      {/* Tracé d'oscilloscope : identité visuelle du produit, purement décoratif. */}
      <svg
        aria-hidden="true"
        viewBox="0 0 1120 60"
        preserveAspectRatio="none"
        className="pointer-events-none absolute inset-0 h-full w-full text-signal/[0.16]"
      >
        <polyline
          className="ecg-trace"
          points="0,30 60,30 74,30 82,10 90,50 98,30 160,30 220,30 234,30 242,14 250,46 258,30 320,30 380,30 394,30 402,10 410,50 418,30 480,30 540,30 554,30 562,14 570,46 578,30 640,30 700,30 714,30 722,10 730,50 738,30 800,30 860,30 874,30 882,14 890,46 898,30 960,30 1020,30 1034,30 1042,10 1050,50 1058,30 1120,30"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>

      <div className="relative">
        <p className="font-caption text-caption text-ink-faint">Signal</p>
        <p className="mt-0.5 font-display text-18 font-bold tracking-tight text-ink">
          {sourcesEnEchec > 0
            ? `Veille dégradée · ${sourcesEnEchec} source${sourcesEnEchec > 1 ? "s" : ""} en échec`
            : "Veille nominale"}
        </p>
      </div>

      <div className="relative ml-auto flex flex-wrap gap-x-7 gap-y-2">
        <div>
          <p className="font-mono-label text-10 uppercase tracking-wider text-ink-faint">
            Dernière collecte
          </p>
          <p className="font-mono-data text-13 text-ink">{dateHeureCourte(derniere, "jamais")}</p>
        </div>
        <div>
          <p className="font-mono-label text-10 uppercase tracking-wider text-ink-faint">
            Sources actives
          </p>
          <p className="font-mono-data text-13 tabular-nums text-ink">
            {actives.length} / {sources.length}
          </p>
        </div>
        <div>
          <p className="font-mono-label text-10 uppercase tracking-wider text-ink-faint">
            Prochain passage
          </p>
          <p className="font-mono-data text-13 text-ink">
            {/* `describe_schedule` cote serveur ecrit deja l'horaire en clair
                (« a 06:17 et 18:17, du lundi au vendredi ») : on le reprend
                tel quel plutot que de reimplementer la lecture du cron. */}
            {planifiees.length > 0 ? planifiees[0].schedule : "aucune planification"}
          </p>
        </div>
      </div>
    </div>
  );
}
