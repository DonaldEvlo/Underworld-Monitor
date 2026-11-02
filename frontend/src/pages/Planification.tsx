import { Link } from "react-router-dom";
import { schedulesApi, type ScheduleApi } from "../api/schedules";
import { CollectesAutomatiques } from "../components/collecte/CollectesAutomatiques";
import { AppLayout } from "../components/layout/AppLayout";
import { useRequete } from "../hooks/useRequete";

/**
 * Planification : ce qui tourne TOUT SEUL.
 *
 * Séparée de la Collecte, qui porte les gestes manuels (lancer, tester). Les
 * deux pages répondent à deux questions distinctes : « que se passe-t-il sans
 * moi ? » et « que puis-je déclencher maintenant ? ».
 */
export function Planification() {
  // Lecture seule : un échec laisse simplement « — », la page reste lisible.
  const requete = useRequete(async () => (await schedulesApi.list()).schedules, []);
  const taches: ScheduleApi[] | null = requete.donnees;

  const actives = taches?.filter((t) => t.enabled) ?? [];
  const suspendues = (taches?.length ?? 0) - actives.length;

  return (
    <AppLayout title="Planification">
      <section className="pulse-panel mb-3.5 flex flex-wrap items-center gap-x-7 gap-y-3 px-5 py-4">
        <div>
          <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">
            Planifications actives
          </p>
          <p className="mt-0.5 font-display text-18 font-bold tracking-tight text-ink">
            {taches === null ? "—" : actives.length}
            {suspendues > 0 && (
              <span className="ml-2 font-mono-data text-13 font-normal text-ink-dim">
                + {suspendues} suspendue(s)
              </span>
            )}
          </p>
        </div>
        <span className="hidden h-10 w-px bg-line md:block" />
        <div className="min-w-0">
          <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">
            Première entrée active
          </p>
          <p className="mt-1 truncate font-mono-data text-14 text-ink">
            {taches === null ? "—" : actives.length > 0 ? actives[0].schedule : "aucune — rien ne tourne sans vous"}
          </p>
        </div>
        <Link
          to="/collecte"
          className="ml-auto rounded-[10px] border border-line bg-panel-sunken px-3.5 py-2 text-13 text-ink transition-colors hover:border-signal/35"
        >
          Lancer une collecte maintenant →
        </Link>
      </section>

      <CollectesAutomatiques />
    </AppLayout>
  );
}
