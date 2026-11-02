import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { lookupApi, type LookupDetection, type LookupResponse } from "../api/lookup";
import { watchlistApi } from "../api/watchlist";
import { useAuth } from "../context/auth-context";
import { peutAdministrer } from "../lib/roles";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { MaskedValue } from "../components/ui/MaskedValue";
import { SeverityBadge } from "../components/ui/SeverityBadge";
import { detectionTypeLabels } from "../lib/taxonomy";
import type { AlertSeverity } from "../types/domain";
import { jour } from "../lib/format";
import { useRequete } from "../hooks/useRequete";

type Surveillance = "inconnue" | "absente" | "deja" | "en-cours" | "erreur";


function libelleType(type: string): string {
  return detectionTypeLabels[type as keyof typeof detectionTypeLabels] ?? type;
}

/** Ce que l'on sait d'une détection, en un mot — jamais le statut technique. */
function etat(d: LookupDetection): { texte: string; classe: string } {
  if (d.corroborated_group) return { texte: `confirmée · ${d.corroborated_group}`, classe: "text-ok" };
  if (d.corroboration_status === "exclusive") return { texte: "vue par nous seuls", classe: "text-ink-dim" };
  return { texte: libelleType(d.type), classe: "text-ink-faint" };
}

const cleMois = (d: Date) => d.getFullYear() * 12 + d.getMonth();

/**
 * Recherche transverse : une valeur, tout ce que la plateforme en sait.
 *
 * ⚠️ Répond au geste le plus banal d'un analyste — « cette organisation
 * est-elle déjà apparue ? » — qui n'avait aucune réponse : la page
 * « Découvrir des sources » cherche de NOUVELLES SOURCES sur des moteurs
 * .onion, et la barre de recherche de l'en-tête était désactivée sur trois
 * pages tout en promettant « Rechercher un indicateur ».
 */
export function Lookup() {
  const [params, setParams] = useSearchParams();
  const requete = params.get("q") ?? "";
  const [saisie, setSaisie] = useState(requete);
  const terme = requete.trim();
  // ⚠️ La requête vit dans l'URL, pour que le résultat soit PARTAGEABLE entre
  // analystes. Une seule réponse retenue : celle du terme affiché.
  const recherche = useRequete(
    async () => {
      const [resultat, liste] = await Promise.all([
        lookupApi.search(terme),
        // La watchlist ne conditionne pas le résultat : si elle échoue, on ne
        // sait simplement pas dire si la valeur est déjà surveillée.
        watchlistApi.list().catch(() => null),
      ]);
      const deja = liste
        ? liste.some((k) => k.term.trim().toLowerCase() === terme.toLowerCase())
        : null;
      return { resultat, deja };
    },
    [terme],
    { actif: terme.length >= 2, garderPendantChargement: false },
  );
  const resultat: LookupResponse | null = terme.length >= 2 ? (recherche.donnees?.resultat ?? null) : null;
  const chargement = recherche.chargement;
  const erreur = recherche.erreur;
  // L'action « mettre sous surveillance » est rattachée au terme : changer de
  // recherche ne doit pas hériter de l'état de la précédente.
  const [actionSurveillance, setActionSurveillance] = useState<{ pour: string; etat: Surveillance } | null>(null);
  const deja = recherche.donnees?.deja;
  const surveillance: Surveillance =
    actionSurveillance && actionSurveillance.pour === terme
      ? actionSurveillance.etat
      : deja == null
        ? "inconnue"
        : deja
          ? "deja"
          : "absente";

  /** Historique mensuel — UNIQUEMENT sur des données complètes.
   *
   * ⚠️ Le serveur tronque la liste des détections (le total réel est à côté).
   * Un histogramme construit sur l'extrait renvoyé dessinerait une activité
   * inventée : des mois vides qui ne le sont pas, un pic qui n'existe pas. On
   * ne le trace que si toutes les détections sont là.
   */
  const historique = useMemo(() => {
    if (!resultat || resultat.detections.length === 0) return null;
    const complet = resultat.total_detections === resultat.detections.length;
    const temps = resultat.detections.map((d) => new Date(d.created_at).getTime());
    const premiere = new Date(Math.min(...temps));
    const derniere = new Date(Math.max(...temps));
    let mois: { n: number; date: Date }[] | null = null;
    if (complet) {
      const debut = cleMois(premiere);
      const nombre = cleMois(derniere) - debut + 1;
      if (nombre <= 36) {
        const compte = new Array<number>(nombre).fill(0);
        for (const t of temps) compte[cleMois(new Date(t)) - debut] += 1;
        mois = compte.map((n, i) => ({
          n,
          date: new Date(Math.floor((debut + i) / 12), (debut + i) % 12, 1),
        }));
      }
    }
    return { complet, premiere, derniere, mois };
  }, [resultat]);

  // Mettre sous surveillance = ecrire dans la watchlist : PEUT_ADMINISTRER.
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);

  async function surveiller() {
    const pour = terme;
    setActionSurveillance({ pour, etat: "en-cours" });
    try {
      await watchlistApi.create({ term: pour });
      setActionSurveillance({ pour, etat: "deja" });
    } catch {
      setActionSurveillance({ pour, etat: "erreur" });
    }
  }

  const maxMois = historique?.mois ? Math.max(1, ...historique.mois.map((m) => m.n)) : 1;
  const nomMois = (d: Date) => d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });

  return (
    <AppLayout title="Rechercher une valeur">
      <div className="flex flex-col gap-3.5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setParams(saisie.trim() ? { q: saisie.trim() } : {});
          }}
          className="pulse-panel p-4"
        >
          <div className="flex gap-2.5">
            <div className="flex h-10 flex-1 items-center gap-2.5 rounded-xl border border-signal/30 bg-panel-sunken px-3.5 focus-within:border-signal/60">
              <Icon name="search" className="text-16 text-ink-faint" />
              <input
                key={requete}
                defaultValue={requete}
                onChange={(e) => setSaisie(e.target.value)}
                autoFocus
                spellCheck={false}
                placeholder="ex : institution-exemple, telecom-exemple.ma, Exemple"
                className="h-full flex-1 bg-transparent font-mono-data text-13 text-ink outline-none placeholder:text-ink-faint"
              />
            </div>
            <button
              type="submit"
              className="rounded-xl bg-signal px-4 text-13 font-semibold text-on-signal transition-opacity hover:opacity-90"
            >
              Rechercher
            </button>
          </div>
          {/* ⚠️ Vrai, et à dire : seule la forme masquée est en base. */}
          <p className="mt-2.5 font-mono-label text-10 text-ink-faint">
            la recherche porte sur les valeurs masquées : un email complet ne trouvera rien, son
            domaine oui · corpus déjà collecté, aucun appel réseau
          </p>
        </form>

        {erreur && (
          <p className="rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
            {erreur}
          </p>
        )}
        {chargement && <p className="text-body-sm text-ink-dim">Recherche…</p>}

        {!chargement && !resultat && !erreur && (
          <p className="text-body-sm text-ink-dim">
            Saisissez au moins deux caractères : un domaine, un nom d&apos;organisation, une valeur
            masquée.
          </p>
        )}

        {resultat && (
          <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_21.5rem]">
            <div className="flex flex-col gap-3.5">
              <section className="rounded-[18px] border border-line bg-panel p-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                    {resultat.total_detections.toLocaleString("fr-FR")} détections ·{" "}
                    {resultat.total_documents.toLocaleString("fr-FR")} documents
                  </h2>
                  {historique && (
                    <span className="font-mono-label text-11 text-ink-faint">
                      première vue {jour(historique.premiere.toISOString())} · dernière{" "}
                      {jour(historique.derniere.toISOString())}
                      {historique.complet
                        ? ""
                        : ` · sur les ${resultat.detections.length} affichées`}
                    </span>
                  )}
                </div>

                {historique?.mois ? (
                  <>
                    <div className="mt-3.5 flex h-[70px] items-end gap-[3px]">
                      {historique.mois.map((m) => (
                        <div
                          key={m.date.getTime()}
                          title={`${nomMois(m.date)} : ${m.n}`}
                          className={`flex-1 rounded-t-[2px] ${m.n > 0 ? "bg-signal/70" : "bg-line"}`}
                          style={{ height: `${m.n > 0 ? Math.max(8, (m.n / maxMois) * 100) : 4}%` }}
                        />
                      ))}
                    </div>
                    <div className="mt-1.5 flex justify-between font-mono-label text-10 text-ink-faint">
                      <span>{nomMois(historique.mois[0].date)}</span>
                      <span>{nomMois(historique.mois[historique.mois.length - 1].date)}</span>
                    </div>
                  </>
                ) : (
                  historique &&
                  !historique.complet && (
                    <p className="mt-2.5 font-mono-label text-10 text-ink-faint">
                      historique non tracé : {resultat.detections.length} détections affichées sur{" "}
                      {resultat.total_detections} — un histogramme sur un extrait serait faux
                    </p>
                  )
                )}

                {resultat.detections.length > 0 ? (
                  <div className="mt-3.5 flex flex-col gap-1.5">
                    {resultat.detections.map((d) => {
                      const e = etat(d);
                      return (
                        <Link
                          key={d.id}
                          to={`/documents?doc=${d.document_id}`}
                          className="grid grid-cols-[minmax(0,1fr)_9rem_8rem_5.5rem] items-center gap-3 rounded-xl border border-line bg-panel-sunken px-3 py-2.5 transition-colors hover:border-signal/30"
                        >
                          <span className="truncate">
                            <MaskedValue value={d.value_masked} />
                          </span>
                          <span className="truncate font-mono-data text-11 text-ink-dim">
                            {d.source_name ?? "—"}
                          </span>
                          <span className={`truncate font-mono-data text-11 ${e.classe}`}>
                            {e.texte}
                          </span>
                          <span className="text-right font-mono-data text-11 text-ink-faint">
                            {jour(d.created_at)}
                          </span>
                        </Link>
                      );
                    })}
                  </div>
                ) : (
                  <p className="mt-3 text-body-sm text-ink-dim">
                    Aucune détection ne porte cette valeur.
                  </p>
                )}
              </section>

              {resultat.total_alerts > 0 && (
                <section className="rounded-[18px] border border-line bg-panel p-4">
                  <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                    Alertes{" "}
                    <span className="font-mono-label text-11 font-normal text-ink-faint">
                      {resultat.total_alerts}
                      {resultat.alerts.length < resultat.total_alerts
                        ? ` · ${resultat.alerts.length} affichées`
                        : ""}
                    </span>
                  </h2>
                  <div className="mt-3 flex flex-col gap-1.5">
                    {resultat.alerts.map((a) => (
                      <Link
                        key={a.id}
                        to={`/alerts/${a.id}`}
                        className="flex flex-wrap items-center gap-2.5 rounded-xl border border-line bg-panel-sunken px-3 py-2.5 transition-colors hover:border-signal/30"
                      >
                        <SeverityBadge severity={a.severity as AlertSeverity} />
                        <span className="font-semibold text-ink">{a.subject}</span>
                        <span className="ml-auto font-mono-label text-11 text-ink-dim">
                          {a.alert_date}
                          {a.corroboration_status === "corroborated" ? " · confirmée" : ""}
                        </span>
                      </Link>
                    ))}
                  </div>
                </section>
              )}

              {resultat.total_documents > 0 && (
                <section className="rounded-[18px] border border-line bg-panel p-4">
                  <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                    Documents{" "}
                    <span className="font-mono-label text-11 font-normal text-ink-faint">
                      {resultat.total_documents}
                      {resultat.documents.length < resultat.total_documents
                        ? ` · ${resultat.documents.length} affichés`
                        : ""}
                    </span>
                  </h2>
                  <div className="mt-3 flex flex-col gap-1.5">
                    {resultat.documents.map((doc) => (
                      <Link
                        key={doc.id}
                        to={`/documents?doc=${doc.id}`}
                        className="flex flex-wrap items-center gap-2.5 rounded-xl border border-line bg-panel-sunken px-3 py-2.5 transition-colors hover:border-signal/30"
                      >
                        <span className="min-w-0 flex-1 truncate text-body-sm text-ink">
                          {doc.title ?? "(sans titre)"}
                        </span>
                        <span className="font-mono-label text-11 text-ink-dim">
                          {doc.source_name}
                          {doc.published_at
                            ? ` · publié le ${jour(doc.published_at)}`
                            : doc.fetched_at
                              ? ` · collecté le ${jour(doc.fetched_at)}`
                              : ""}
                        </span>
                      </Link>
                    ))}
                  </div>
                </section>
              )}
            </div>

            <aside className="flex flex-col gap-3.5">
              <section className="pulse-panel p-4">
                <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                  Rattachement
                </h2>
                {resultat.entities.length > 0 ? (
                  <div className="mt-2.5 flex flex-col gap-2">
                    {resultat.entities.map((e) => (
                      <Link
                        key={e.id}
                        to="/entities"
                        className={`rounded-xl border bg-panel-sunken px-3 py-2.5 transition-colors ${
                          e.active ? "border-signal/25 hover:border-signal/45" : "border-line"
                        }`}
                      >
                        <p className="text-body-sm font-semibold text-ink">{e.name}</p>
                        <p className="mt-0.5 font-mono-label text-11 text-ink-dim">
                          {e.matched_selector ? `sélecteur ${e.matched_selector}` : "nom seulement"} ·{" "}
                          {e.active ? "surveillance active" : "inactive"}
                        </p>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-body-sm text-ink-dim">
                    Aucune organisation surveillée ne correspond : la valeur est vue, mais personne ne
                    la surveille.
                  </p>
                )}
              </section>

              {admin && (
              <section className="rounded-[18px] border border-line bg-panel p-4">
                <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                  Mettre sous surveillance
                </h2>
                {/* ⚠️ La maquette promettait « alerte à la prochaine
                    réapparition ». C'est faux : la watchlist marque les
                    documents comme PERTINENTS, elle ne crée aucune alerte —
                    seule une organisation déclarée avec un sélecteur en
                    produit. Le libellé dit ce que fait le bouton. */}
                <p className="mt-1 text-body-sm text-ink-dim">
                  Les documents qui contiendront <span className="font-mono-data">{requete}</span>{" "}
                  seront marqués pertinents. Cela ne crée pas d&apos;alerte : pour alerter, déclarez
                  une organisation avec ce sélecteur.
                </p>
                {surveillance === "deja" ? (
                  <p className="mt-3 rounded-[10px] border border-signal/30 bg-signal/[0.08] px-3 py-2 text-center text-body-sm text-signal">
                    Déjà dans la watchlist
                  </p>
                ) : (
                  <button
                    onClick={() => void surveiller()}
                    disabled={surveillance === "en-cours" || surveillance === "inconnue"}
                    className="mt-3 w-full rounded-[10px] bg-signal py-2.5 text-13 font-semibold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-40"
                  >
                    {surveillance === "en-cours" ? "Ajout…" : "Ajouter à la watchlist"}
                  </button>
                )}
                {surveillance === "erreur" && (
                  <p className="mt-2 text-body-sm text-critical">L&apos;ajout a échoué.</p>
                )}
                {surveillance === "inconnue" && (
                  <p className="mt-2 font-mono-label text-10 text-ink-faint">
                    watchlist injoignable : impossible de savoir si la valeur y est déjà
                  </p>
                )}
              </section>
              )}
            </aside>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
