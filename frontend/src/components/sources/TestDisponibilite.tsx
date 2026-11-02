import type { SourceTestEntry } from "../../api/sources";
import { lancerTestSources, useTestSources } from "../../hooks/useTestSources";
import { useAuth } from "../../context/auth-context";
import { peutAdministrer } from "../../lib/roles";
import { ageRelatif } from "../../lib/alertes";
import {
  dureeDepuis,
  estNonConcluant,
  etatTestAffiche,
  libellePortee,
  preuveCollecte,
  rangAffichage,
} from "../../lib/testSources";
import { Icon } from "../ui/Icon";
import { dateHeure } from "../../lib/format";

const BOUTON =
  "flex w-full items-center justify-center gap-2 rounded-[10px] border border-line bg-panel-sunken px-3 py-2 text-body-sm text-ink transition-colors hover:border-signal/35 disabled:opacity-50";

/** État d'une source dans un test, en une ligne (tableau des sources). */
export function PastilleTest({ entree }: { entree: SourceTestEntry }) {
  const a = etatTestAffiche(entree);
  return (
    <span className={`inline-flex items-center gap-1.5 font-mono-label text-10 ${a.ton}`}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${a.point} ${a.anime ? "animate-pulse" : ""}`} />
      test : {a.texte}
      {estNonConcluant(entree) && <span className="text-ink-faint">· {preuveCollecte(entree)}</span>}
    </span>
  );
}

interface Props {
  nbActives: number;
  nbTotal: number;
  /** Source sélectionnée (page Collecte) : propose de la tester seule. */
  sourceSelectionnee?: { id: string; name: string } | null;
  /** Liste détaillée des résultats. Masquée quand le tableau des sources
   * affiche déjà l'état de chaque ligne. */
  afficherListe?: boolean;
}

/**
 * Test de disponibilité des sources, avec retour en continu.
 *
 * ⚠️ Le test dure plusieurs minutes (deux passes via Tor, délais de
 * politesse). Il affichait « Test en cours… » puis rien : l'analyste ne
 * savait ni où il en était, ni pourquoi c'était long. L'écran dit désormais
 * quelle passe tourne, combien de sources sont faites, et le résultat de
 * chacune dès qu'il arrive.
 */
export function TestDisponibilite({ nbActives, nbTotal, sourceSelectionnee, afficherListe = true }: Props) {
  const { job, demarrage, erreur } = useTestSources();
  // ⚠️ LANCER un test est en PEUT_ADMINISTRER (il sort du trafic Tor) ;
  // en LIRE le dernier résultat ne l'est pas. L'analyste garde donc la
  // progression et les pastilles d'état, il perd les trois boutons.
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);
  const enCours = job?.status === "running";
  const occupe = enCours || demarrage;

  const fait = job ? job.first_pass_done + job.retry_done : 0;
  const aFaire = job ? Math.max(1, job.total + job.retry_total) : 1;
  const enAttente = job ? job.entries.filter((e) => e.state === "pending" || e.state === "retrying").length : 0;
  const tries = job ? [...job.entries].sort((x, y) => rangAffichage(x) - rangAffichage(y)) : [];
  // Les négatifs sur une source qui exige un navigateur ne sont PAS des
  // pannes : comptés à part (voir lib/testSources).
  const nonConcluants = job ? job.entries.filter(estNonConcluant).length : 0;
  const injoignables = job ? job.unreachable - nonConcluants : 0;
  const concluants = job ? job.total - nonConcluants : 0;

  return (
    <div className="flex flex-col gap-2.5">
      {admin && (
      <div className="flex flex-col gap-2">
        {sourceSelectionnee && (
          <button
            onClick={() => void lancerTestSources({ sourceId: sourceSelectionnee.id })}
            disabled={occupe}
            title="Vérifie que la source répond encore, via Tor — sans rien collecter ni modifier"
            className={BOUTON}
          >
            Tester « {sourceSelectionnee.name} »
          </button>
        )}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => void lancerTestSources({ onlyActive: true })}
            disabled={occupe || nbActives === 0}
            title="Teste via Tor les sources actives — celles que la collecte utilise réellement"
            className={BOUTON}
          >
            Tester les {nbActives} actives
          </button>
          <button
            onClick={() => void lancerTestSources({ onlyActive: false })}
            disabled={occupe || nbTotal === 0}
            title="Teste via Tor toutes les sources, inactives comprises — pour repérer une source désactivée redevenue joignable"
            className={BOUTON}
          >
            Tester les {nbTotal} (inactives incl.)
          </button>
        </div>
      </div>
      )}

      {demarrage && (
        <p className="flex items-center gap-2 text-body-sm text-ink-dim">
          <Icon name="progress_activity" className="animate-spin text-15" />
          Lancement du test…
        </p>
      )}

      {erreur && <p className="text-12 text-critical">{erreur}</p>}

      {job && (
        <div
          className={`rounded-xl border p-3 ${
            job.status === "error" ? "border-critical/35 bg-critical/[0.06]" : enCours ? "border-signal/30 bg-signal/[0.04]" : "border-line bg-panel-sunken"
          }`}
        >
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-12">
            {enCours && <Icon name="progress_activity" className="animate-spin text-14 text-signal" />}
            <span className="font-semibold text-ink">
              {enCours ? "Test en cours" : job.status === "error" ? "Test interrompu" : "Dernier test"}
            </span>
            <span className="rounded-md border border-line px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
              {libellePortee(job)}
            </span>
            <span className="ml-auto font-mono-label text-10 text-ink-faint" title={dateHeure(job.started_at)}>
              {enCours
                ? `depuis ${dureeDepuis(job.started_at)}`
                : job.finished_at
                  ? `${ageRelatif(job.finished_at)} · durée ${dureeDepuis(job.started_at, job.finished_at)}`
                  : ""}
            </span>
          </div>

          {enCours && (
            <>
              <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-panel-raised">
                <div className="h-full bg-signal transition-all duration-500" style={{ width: `${Math.round((100 * fait) / aFaire)}%` }} />
              </div>
              <p className="mt-1.5 font-mono-label text-11 text-ink-dim">
                {job.total === 0
                  ? "préparation…"
                  : job.phase === "retry"
                    ? `Seconde passe : ${job.retry_done}/${job.retry_total} échec(s) re-testé(s) après renouvellement du circuit Tor`
                    : `Première passe via Tor : ${job.first_pass_done}/${job.total} source(s) testée(s)`}
              </p>
            </>
          )}

          {job.total > 0 && (
            <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono-data text-12">
              <span className="text-ok">{job.reachable} joignable(s)</span>
              <span className="text-critical">{injoignables} injoignable(s)</span>
              {nonConcluants > 0 && (
                <span
                  className="text-info"
                  title="Sources qui exigent un navigateur : le test envoie une requête HTTP simple, qu'elles filtrent. Leur dernière collecte réussie fait foi."
                >
                  {nonConcluants} non concluant(s)
                </span>
              )}
              {enAttente > 0 && <span className="text-ink-faint">{enAttente} en attente</span>}
              {!enCours && job.status === "done" && concluants > 0 && (
                <span className="text-ink-dim">
                  {Math.round((100 * job.reachable) / concluants)} % des tests concluants
                </span>
              )}
            </p>
          )}

          {job.error && <p className="mt-2 text-12 text-critical">{job.error}</p>}

          {afficherListe && tries.length > 0 && (
            <ul className="custom-scrollbar mt-2.5 max-h-64 space-y-1 overflow-y-auto border-t border-line-soft pt-2">
              {tries.map((e) => {
                const a = etatTestAffiche(e);
                return (
                  <li key={e.source_id} className="flex items-center gap-2 text-11.5">
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${a.point} ${a.anime ? "animate-pulse" : ""}`} />
                    <span className="min-w-0 truncate text-ink">{e.name}</span>
                    {!e.active && <span className="shrink-0 rounded border border-line px-1 text-10 text-ink-dim">inactive</span>}
                    <span className={`ml-auto shrink-0 text-right font-mono-label text-10 ${a.ton}`}>
                      {a.texte}
                      {estNonConcluant(e) && <span className="block text-ink-faint">{preuveCollecte(e)}</span>}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      <p className="font-mono-label text-10 leading-[15px] text-ink-faint">
        « Non concluant » : la source exige un navigateur ; sa dernière collecte réussie fait foi.
      </p>
    </div>
  );
}
