import { useState } from "react";
import {
  schedulesApi,
  type ScheduleActionApi,
  type ScheduleApi,
  type SchedulePayload,
} from "../../api/schedules";
import { Icon } from "../ui/Icon";
import { useAuth } from "../../context/auth-context";
import { peutAdministrer } from "../../lib/roles";
import { LectureSeule } from "../ui/LectureSeule";
import { dateHeure } from "../../lib/format";
import { useRequete } from "../../hooks/useRequete";


function dureeLisible(secondes: number): string {
  if (secondes < 60) return `${secondes} s`;
  const minutes = Math.round(secondes / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;
}

// ⚠️ `skipped` n'est PAS un échec : c'est une tâche suspendue au moment où Beat
// l'a déclenchée. Les confondre ferait passer un réglage volontaire pour une
// panne.
const ETATS: Record<string, { libelle: string; classe: string }> = {
  success: { libelle: "réussie", classe: "text-ok" },
  error: { libelle: "en échec", classe: "text-error" },
  skipped: { libelle: "suspendue", classe: "text-on-surface-variant" },
};

// ⚠️ Numérotation de Celery : 0 = dimanche, 6 = samedi. L'ordre d'affichage
// commence au lundi (usage français), l'ordre envoyé est numérique.
const JOURS = [
  { valeur: 1, court: "L", nom: "lundi" },
  { valeur: 2, court: "M", nom: "mardi" },
  { valeur: 3, court: "M", nom: "mercredi" },
  { valeur: 4, court: "J", nom: "jeudi" },
  { valeur: 5, court: "V", nom: "vendredi" },
  { valeur: 6, court: "S", nom: "samedi" },
  { valeur: 0, court: "D", nom: "dimanche" },
];

const TOUS_LES_JOURS = JOURS.map((j) => j.valeur);

/** Jours désignés par un champ crontab. « * » vaut la semaine entière. */
function joursDepuisCron(champ: string): number[] {
  const valeur = champ.trim();
  if (!valeur || valeur === "*" || valeur.startsWith("*/")) return [...TOUS_LES_JOURS];
  const jours = new Set<number>();
  for (const morceau of valeur.split(",")) {
    if (morceau.includes("-")) {
      const [debut, fin] = morceau.split("-").map(Number);
      for (let j = debut; j <= fin; j += 1) jours.add(j);
    } else if (morceau.trim() !== "") {
      jours.add(Number(morceau));
    }
  }
  return [...jours];
}

/** Les 7 jours valent « * » : énumérer serait exact mais illisible. */
function cronDepuisJours(jours: number[]): string {
  if (jours.length === 0 || jours.length === TOUS_LES_JOURS.length) return "*";
  return [...jours].sort((a, b) => a - b).join(",");
}

const FORMULAIRE_VIDE: SchedulePayload = {
  label: "",
  action: "",
  cron_minute: "0",
  cron_hour: "6",
  cron_day_of_week: "*",
};

const CLASSE_CHAMP =
  "rounded-md border border-outline-variant bg-surface-dim px-2.5 py-1.5 text-body-sm text-on-surface transition-colors focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/40";
const CLASSE_LABEL =
  "font-mono-label text-10 uppercase tracking-wider text-on-surface-variant";

export function CollectesAutomatiques() {
  // ⚠️ LECTURE OUVERTE A L'ANALYSTE, ECRITURE NON — c'est une decision
  // ecrite : la fraicheur de ses alertes depend de la date de la derniere
  // collecte, il doit pouvoir la LIRE sans pouvoir la MODIFIER. Le routeur
  // `schedules` est en PEUT_VOIR_LE_CORPUS, ses ecritures en
  // PEUT_ADMINISTRER.
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);
  const requete = useRequete(() => schedulesApi.list(), []);
  const schedules: ScheduleApi[] = requete.donnees?.schedules ?? [];
  const actions: ScheduleActionApi[] = requete.donnees?.actions ?? [];
  const delaiRelecture = requete.donnees?.reload_delay_seconds ?? 60;
  const loading = requete.chargement;
  // Erreur d'une ACTION (ajout, modification, suppression), distincte du chargement.
  const [erreurAction, setError] = useState<string | null>(null);
  const error = requete.erreur ?? erreurAction;
  const modifierRequete = requete.modifier;
  const setSchedules = (fn: (precedent: ScheduleApi[]) => ScheduleApi[]) =>
    modifierRequete((r) => (r ? { ...r, schedules: fn(r.schedules) } : r));
  const [busy, setBusy] = useState<string | null>(null);

  // `null` = aucun formulaire ; "" = création ; un id = modification.
  const [editionId, setEditionId] = useState<string | null>(null);
  const [formulaire, setFormulaire] = useState<SchedulePayload>(FORMULAIRE_VIDE);
  const [jours, setJours] = useState<number[]>([...TOUS_LES_JOURS]);
  // Suppression en deux temps : un clic arme, le second confirme. Un
  // `window.confirm` bloquerait le rendu et ne serait pas vérifiable au test.
  const [aSupprimer, setASupprimer] = useState<string | null>(null);


  function ouvrirCreation() {
    setError(null);
    setASupprimer(null);
    setEditionId("");
    setFormulaire({ ...FORMULAIRE_VIDE, action: actions[0]?.action ?? "" });
    setJours([...TOUS_LES_JOURS]);
  }

  function ouvrirModification(entree: ScheduleApi) {
    setError(null);
    setASupprimer(null);
    setEditionId(entree.id);
    setFormulaire({
      label: entree.label,
      action: entree.action,
      cron_minute: entree.cron_minute,
      cron_hour: entree.cron_hour,
      cron_day_of_week: entree.cron_day_of_week,
    });
    setJours(joursDepuisCron(entree.cron_day_of_week));
  }

  function basculerJour(valeur: number) {
    setJours((prec) =>
      prec.includes(valeur) ? prec.filter((j) => j !== valeur) : [...prec, valeur],
    );
  }

  async function enregistrer() {
    setBusy("form");
    setError(null);
    const charge = { ...formulaire, cron_day_of_week: cronDepuisJours(jours) };
    try {
      if (editionId) {
        const maj = await schedulesApi.update(editionId, charge);
        setSchedules((prec) => prec.map((s) => (s.id === maj.id ? maj : s)));
      } else {
        const cree = await schedulesApi.create(charge);
        setSchedules((prec) => [...prec, cree]);
      }
      setEditionId(null);
    } catch (err) {
      // Le message du serveur est explicite (action inconnue, horaire invalide,
      // nom déjà pris) : le reproduire tel quel plutôt que le résumer.
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setBusy(null);
    }
  }

  async function supprimer(entree: ScheduleApi) {
    setBusy(entree.id);
    setError(null);
    try {
      await schedulesApi.remove(entree.id);
      setSchedules((prec) => prec.filter((s) => s.id !== entree.id));
      setASupprimer(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setBusy(null);
    }
  }

  async function basculer(entree: ScheduleApi) {
    setBusy(entree.id);
    setError(null);
    try {
      const maj = await schedulesApi.update(entree.id, { enabled: !entree.enabled });
      setSchedules((prec) => prec.map((s) => (s.id === maj.id ? maj : s)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setBusy(null);
    }
  }

  const actionChoisie = actions.find((a) => a.action === formulaire.action);
  // ⚠️ Zéro jour coché voudrait dire « jamais ». On le bloque explicitement
  // plutôt que de le convertir en « tous les jours » dans le dos de l'analyste.
  const aucunJour = jours.length === 0;
  const formulaireIncomplet =
    !formulaire.label.trim() || !formulaire.action || aucunJour;

  return (
    <div className="rounded-lg border border-outline-variant bg-surface-container p-4">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
          <Icon name="schedule" className="text-primary" />
          Collectes automatiques
        </h3>
        {admin && (
          <button
            onClick={ouvrirCreation}
            disabled={actions.length === 0}
            className="flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1.5 font-mono-data text-11 text-primary transition-colors hover:bg-primary/20 disabled:opacity-40"
          >
            <Icon name="add" className="text-14" />
            Ajouter un moment
          </button>
        )}
      </div>

      {/* ⚠️ Un changement n'est pas instantané : Beat relit la base
          périodiquement. Sans cette phrase, un horaire modifié qui ne bouge pas
          pendant une minute passerait pour une panne. */}
      {admin ? (
        <p className="mb-3 text-body-sm text-on-surface-variant">
          Les horaires sont lus en base : un ajout, une modification ou une suppression
          prend effet sous {dureeLisible(delaiRelecture)}, sans redémarrer le service.
        </p>
      ) : (
        <LectureSeule quoi="la modification des horaires" />
      )}

      {error && (
        <p className="mb-3 rounded-md border border-error/40 bg-error-container/20 p-2 text-body-sm text-error">
          {error}
        </p>
      )}

      {editionId !== null && (
        <div className="mb-4 overflow-hidden rounded-lg border border-primary/25 bg-surface-container-low">
          <div className="flex items-center justify-between border-b border-outline-variant/60 bg-surface-bright/60 px-4 py-2.5">
            <p className="flex items-center gap-2 font-bold text-body-sm text-on-surface">
              <Icon
                name={editionId ? "edit_calendar" : "more_time"}
                className="text-16 text-primary"
              />
              {editionId ? "Modifier le moment" : "Nouveau moment de collecte"}
            </p>
            <button
              onClick={() => setEditionId(null)}
              aria-label="Fermer"
              className="rounded p-0.5 text-on-surface-variant transition-colors hover:bg-surface-bright hover:text-on-surface"
            >
              <Icon name="close" className="text-16" />
            </button>
          </div>

          <div className="flex flex-col gap-4 p-4">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className={CLASSE_LABEL}>Nom</span>
                <input
                  value={formulaire.label}
                  onChange={(e) => setFormulaire({ ...formulaire, label: e.target.value })}
                  placeholder="Collecte du matin"
                  className={CLASSE_CHAMP}
                />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className={CLASSE_LABEL}>Type d&apos;action</span>
                <select
                  value={formulaire.action}
                  onChange={(e) => setFormulaire({ ...formulaire, action: e.target.value })}
                  className={CLASSE_CHAMP}
                >
                  {actions.map((a) => (
                    <option key={a.action} value={a.action}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {/* La file n'est pas un choix : elle découle de l'action. On
                l'affiche pour que l'analyste sache qu'une tâche longue ne
                bloquera pas l'alerting. */}
            {actionChoisie && (
              <p className="-mt-2 flex flex-wrap items-center gap-2 text-body-sm text-on-surface-variant">
                <span className="rounded border border-outline-variant px-1.5 py-0.5 font-mono-label text-10">
                  file {actionChoisie.queue}
                </span>
                <span className="opacity-80">{actionChoisie.description}</span>
              </p>
            )}

            <div className="grid gap-4 sm:grid-cols-[auto_auto_1fr] sm:items-start">
              <label className="flex flex-col gap-1.5">
                <span className={CLASSE_LABEL}>Heure(s)</span>
                <input
                  value={formulaire.cron_hour}
                  onChange={(e) => setFormulaire({ ...formulaire, cron_hour: e.target.value })}
                  className={`${CLASSE_CHAMP} w-28 font-mono-data`}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className={CLASSE_LABEL}>Minute</span>
                <input
                  value={formulaire.cron_minute}
                  onChange={(e) => setFormulaire({ ...formulaire, cron_minute: e.target.value })}
                  className={`${CLASSE_CHAMP} w-24 font-mono-data`}
                />
              </label>

              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap items-baseline gap-3">
                  <span className={CLASSE_LABEL}>Jours</span>
                  {/* Raccourcis : les trois cas courants, sans empêcher un
                      choix libre jour par jour. */}
                  <div className="flex gap-2 font-mono-label text-10 text-on-surface-variant">
                    <button
                      onClick={() => setJours([...TOUS_LES_JOURS])}
                      className="underline-offset-2 transition-colors hover:text-primary hover:underline"
                    >
                      tous
                    </button>
                    <button
                      onClick={() => setJours([1, 2, 3, 4, 5])}
                      className="underline-offset-2 transition-colors hover:text-primary hover:underline"
                    >
                      semaine
                    </button>
                    <button
                      onClick={() => setJours([0, 6])}
                      className="underline-offset-2 transition-colors hover:text-primary hover:underline"
                    >
                      week-end
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {JOURS.map((jour) => {
                    const actif = jours.includes(jour.valeur);
                    return (
                      <button
                        key={jour.valeur}
                        onClick={() => void basculerJour(jour.valeur)}
                        aria-pressed={actif}
                        title={jour.nom}
                        className={`h-8 w-8 rounded-md border font-mono-data text-12 transition-colors ${
                          actif
                            ? "border-primary bg-primary text-on-primary"
                            : "border-outline-variant bg-surface-dim text-on-surface-variant hover:border-outline hover:text-on-surface"
                        }`}
                      >
                        {jour.court}
                      </button>
                    );
                  })}
                </div>
                {aucunJour && (
                  <span className="font-mono-label text-10 text-error">
                    Aucun jour sélectionné : la collecte ne se déclencherait jamais.
                  </span>
                )}
              </div>
            </div>

            <p className="font-mono-label text-10 text-on-surface-variant opacity-80">
              Heures et minutes au format Celery : 6 · 6,18 (deux passages) ·{" "}
              {"*/4"} (toutes les 4 h) · * (toutes).
            </p>

            <div className="flex gap-2 border-t border-outline-variant/60 pt-3">
              <button
                onClick={() => void enregistrer()}
                disabled={busy === "form" || formulaireIncomplet}
                className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 font-mono-data text-11 font-bold text-on-primary transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <Icon name="check" className="text-14" />
                Enregistrer
              </button>
              <button
                onClick={() => setEditionId(null)}
                className="flex items-center gap-1 rounded-md border border-outline-variant px-3 py-1.5 font-mono-data text-11 text-on-surface-variant transition-colors hover:bg-surface-bright"
              >
                Annuler
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-body-sm text-on-surface-variant">Chargement…</p>
      ) : schedules.length === 0 ? (
        // ⚠️ Aucune entrée = aucune collecte automatique. À dire franchement :
        // une liste vide se lirait sinon comme un chargement raté.
        <p className="text-body-sm text-on-surface-variant">
          Aucun moment de collecte : rien ne se déclenche automatiquement.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {schedules.map((entree) => {
            const etat = entree.last_status ? ETATS[entree.last_status] : null;
            return (
              <div
                key={entree.id}
                className={`flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 transition-opacity ${
                  entree.enabled
                    ? "border-outline-variant/60"
                    : "border-outline-variant/40 opacity-60"
                }`}
              >
                <div className="min-w-[16rem] flex-1">
                  <p className="font-bold text-on-surface">
                    {entree.label}
                    {!entree.enabled && (
                      <span className="ml-2 rounded border border-outline-variant px-1.5 py-0.5 font-mono-label text-10 text-on-surface-variant">
                        suspendue
                      </span>
                    )}
                  </p>
                  <p className="font-mono-label text-11 text-on-surface-variant">
                    {entree.action_label} · <span className="text-primary/80">{entree.schedule}</span>{" "}
                    · file {entree.queue}
                  </p>
                  <p className="mt-0.5 font-mono-label text-11 text-on-surface-variant">
                    {entree.last_run_at ? (
                      <>
                        Dernier passage {dateHeure(entree.last_run_at)}
                        {etat && <span className={` ${etat.classe}`}> · {etat.libelle}</span>}
                        {entree.last_duration_seconds !== null &&
                          ` · ${dureeLisible(entree.last_duration_seconds)}`}
                      </>
                    ) : (
                      // Jamais passée n'est pas la même chose qu'en échec.
                      <span className="opacity-70">Aucun passage enregistré</span>
                    )}
                  </p>
                  {entree.last_detail && (
                    <p className="mt-0.5 truncate font-mono-label text-10 text-on-surface-variant opacity-70">
                      {entree.last_detail}
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-1">
                  {!admin ? null : aSupprimer === entree.id ? (
                    <>
                      <span className="font-mono-label text-11 text-error">Supprimer ?</span>
                      <button
                        onClick={() => void supprimer(entree)}
                        disabled={busy === entree.id}
                        className="rounded-md border border-error/40 bg-error-container/20 px-2 py-1 font-mono-data text-11 text-error transition-colors hover:bg-error-container/40 disabled:opacity-40"
                      >
                        Confirmer
                      </button>
                      <button
                        onClick={() => setASupprimer(null)}
                        className="rounded-md border border-outline-variant px-2 py-1 font-mono-data text-11 text-on-surface-variant transition-colors hover:bg-surface-bright"
                      >
                        Annuler
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => void basculer(entree)}
                        disabled={busy === entree.id}
                        title={entree.enabled ? "Suspendre" : "Réactiver"}
                        className={`flex items-center gap-1 rounded-md border px-2 py-1 font-mono-data text-11 transition-colors disabled:opacity-40 ${
                          entree.enabled
                            ? "border-outline-variant text-on-surface-variant hover:bg-surface-bright"
                            : "border-primary/30 bg-primary/10 text-primary hover:bg-primary/20"
                        }`}
                      >
                        <Icon
                          name={entree.enabled ? "pause" : "play_arrow"}
                          className="text-14"
                        />
                        {entree.enabled ? "Suspendre" : "Réactiver"}
                      </button>
                      <button
                        onClick={() => ouvrirModification(entree)}
                        className="flex items-center gap-1 rounded-md border border-outline-variant px-2 py-1 font-mono-data text-11 text-on-surface-variant transition-colors hover:bg-surface-bright"
                      >
                        <Icon name="edit" className="text-14" />
                        Modifier
                      </button>
                      <button
                        onClick={() => setASupprimer(entree.id)}
                        className="flex items-center gap-1 rounded-md border border-outline-variant px-2 py-1 font-mono-data text-11 text-on-surface-variant transition-colors hover:bg-surface-bright hover:text-error"
                      >
                        <Icon name="delete" className="text-14" />
                        Supprimer
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
