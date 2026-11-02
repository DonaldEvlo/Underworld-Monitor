import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { alertsApi, type AlertApi, type DigestResponse } from "../api/alerts";
import { entitiesApi, type EntityApi } from "../api/entities";
import { AppLayout } from "../components/layout/AppLayout";
import { BoutonExport } from "../components/ui/BoutonExport";
import { Icon } from "../components/ui/Icon";
import { useAuth } from "../context/auth-context";
import { peutAdministrer } from "../lib/roles";
import { invaliderBadges } from "../hooks/useVeilleBadges";
import { domaineAlerte, parGraviteEtFraicheur, sujetAlerte } from "../lib/alertes";
import { severityLabels, severityPuce } from "../lib/taxonomy";
import type { AlertSeverity, AlertStatus } from "../types/domain";
import { jour } from "../lib/format";
import { useRequete } from "../hooks/useRequete";
import { DeleteAllAlertsConfirmModal } from "../components/alertes/ConfirmationSuppressionAlertes";
import { EnteteListeAlertes, LigneAlerte } from "../components/alertes/LigneAlerte";

const PAGE_SIZE = 25;

// « Toutes » en dernier : la vue par défaut est la file de travail (ouvertes).
const ONGLETS_STATUT: { id: AlertStatus | ""; label: string }[] = [
  { id: "open", label: "Ouvertes" },
  { id: "acknowledged", label: "Acquittées" },
  { id: "resolved", label: "Résolues" },
  { id: "", label: "Toutes" },
];

// Du plus grave au moins grave : l'ordre de lecture d'un analyste.
const GRAVITES: AlertSeverity[] = ["critical", "high", "medium", "low"];


/**
 * La liste des alertes — une file, pas un tableau.
 *
 * ⚠️ Une alerte était une ligne de SEPT COLONNES, avec résumé, actions et
 * pièces justificatives entassés dedans. Tout cela vit désormais dans le
 * DOSSIER (`/alerts/:id`) ; la liste ne sert plus qu'à choisir par où
 * commencer, et chaque ligne y mène.
 */
export function Alerts() {
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<AlertStatus | "">("open");
  // Filtre SERVEUR : le total suit le filtre. Un tri fait après coup dans la
  // page ferait annoncer plus d'alertes que la liste n'en sert.
  const [severities, setSeverities] = useState<AlertSeverity[]>([]);
  const [alertDate, setAlertDate] = useState("");
  // Groupe : ses alertes ET celles de ses filiales. Lu dans l'adresse
  // (`?groupe=`) pour que la vue Périmètre puisse y mener directement.
  const [params, setParams] = useSearchParams();
  const groupId = params.get("groupe") ?? "";
  function choisirGroupe(id: string) {
    setOffset(0);
    setParams(
      (prec) => {
        const p = new URLSearchParams(prec);
        if (id) p.set("groupe", id);
        else p.delete("groupe");
        return p;
      },
      { replace: true },
    );
  }
  // Incrémenté après une génération ou une suppression : les compteurs doivent
  // se recalculer, pas seulement la liste.
  const [version, setVersion] = useState(0);

  const [digest, setDigest] = useState<DigestResponse | null>(null);
  const [digestLoading, setDigestLoading] = useState(false);
  const [digestError, setDigestError] = useState<string | null>(null);

  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [showDeleteAll, setShowDeleteAll] = useState(false);
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);
  const [deleteAllSummary, setDeleteAllSummary] = useState<{ deleted_count: number } | null>(null);

  // Filtrage côté client sur la page servie (25 lignes) : un aller-retour
  // serveur à chaque frappe n'apporterait rien.
  const [search, setSearch] = useState("");

  // Pas bloquants : sans les noms on retombe sur l'identifiant, sans la liste
  // des journées le sélecteur reste vide.
  const entitesReq = useRequete(
    async () => Object.fromEntries((await entitiesApi.list()).map((e) => [e.id, e])) as Record<string, EntityApi>,
    [],
  );
  const datesReq = useRequete(async () => (await alertsApi.dates()).dates, []);
  const entitiesById: Record<string, EntityApi> = entitesReq.donnees ?? {};
  const availableDates: string[] = datesReq.donnees ?? [];

  // Une réponse périmée (filtre changé entre-temps) est ignorée, et
  // « en chargement » se déduit des filtres courants (voir useRequete).
  const cleGravites = severities.join(",");
  const listeReq = useRequete(
    () =>
      alertsApi.list({
        status: status || undefined,
        severities: severities.length ? severities : undefined,
        alertDate: alertDate || undefined,
        groupId: groupId || undefined,
        offset,
        limit: PAGE_SIZE,
      }),
    [status, cleGravites, alertDate, groupId, offset, version],
  );
  // Après « tout supprimer », la liste se vide immédiatement, sans attendre
  // le rechargement.
  const vide = deleteAllSummary !== null && listeReq.chargement;
  const items: AlertApi[] = vide ? [] : (listeReq.donnees?.items ?? []);
  const total = vide ? 0 : (listeReq.donnees?.total ?? 0);
  const loading = listeReq.chargement;
  const loadError = listeReq.erreur;

  // Les compteurs des onglets et des pastilles portent sur le MÊME périmètre
  // qu'ils décrivent : un onglet « Ouvertes · 32 » au-dessus d'une liste
  // filtrée sur « critique » qui n'en montre qu'une mentirait.
  const comptesStatutReq = useRequete(
    async () =>
      Object.fromEntries(
        await Promise.all(
          ONGLETS_STATUT.map((o) =>
            alertsApi
              .list({
                status: o.id || undefined,
                severities: severities.length ? severities : undefined,
                alertDate: alertDate || undefined,
                groupId: groupId || undefined,
                limit: 1,
              })
              .then((r) => [o.id, r.total] as const),
          ),
        ),
      ) as Record<string, number>,
    [cleGravites, alertDate, groupId, version],
  );
  const comptesGraviteReq = useRequete(
    async () =>
      Object.fromEntries(
        await Promise.all(
          GRAVITES.map((g) =>
            alertsApi
              .list({
                status: status || undefined,
                severities: [g],
                alertDate: alertDate || undefined,
                groupId: groupId || undefined,
                limit: 1,
              })
              .then((r) => [g, r.total] as const),
          ),
        ),
      ) as Partial<Record<AlertSeverity, number>>,
    [status, alertDate, groupId, version],
  );
  const comptesStatut: Record<string, number> = comptesStatutReq.donnees ?? {};
  const comptesGravite: Partial<Record<AlertSeverity, number>> = comptesGraviteReq.donnees ?? {};

  function toggleSeverity(valeur: AlertSeverity) {
    setOffset(0);
    setSeverities((prec) =>
      prec.includes(valeur) ? prec.filter((s) => s !== valeur) : [...prec, valeur],
    );
  }

  function reinitialiser() {
    setOffset(0);
    setStatus("");
    setSeverities([]);
    setAlertDate("");
    choisirGroupe("");
  }

  async function handleDigest() {
    setDigestLoading(true);
    setDigestError(null);
    try {
      // ⚠️ Le résumé porte sur le MÊME périmètre que la liste affichée.
      setDigest(
        await alertsApi.digest({
          severities: severities.length ? severities : undefined,
          alertDate: alertDate || undefined,
          status: status || undefined,
          groupId: groupId || undefined,
        }),
      );
    } catch (err) {
      setDigestError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setDigestLoading(false);
    }
  }

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await alertsApi.generate();
      setVersion((v) => v + 1);
      invaliderBadges();
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setGenerating(false);
    }
  }

  async function handleDeleteAll() {
    const result = await alertsApi.deleteAll();
    setShowDeleteAll(false);
    setOffset(0);
    setDeleteAllSummary(result);
    setVersion((v) => v + 1);
    invaliderBadges();
  }

  const normalizedSearch = search.trim().toLowerCase();
  const filteredItems = normalizedSearch
    ? items.filter((alert) => {
        const nom = sujetAlerte(alert, entitiesById);
        return (
          nom.toLowerCase().includes(normalizedSearch) ||
          (alert.summary ?? "").toLowerCase().includes(normalizedSearch) ||
          (domaineAlerte(alert, entitiesById) ?? "").includes(normalizedSearch)
        );
      })
    : items;

  // Gravité d'abord, fraîcheur ensuite — même comparateur que le poste de
  // veille (`lib/alertes.ts`), pour que les deux écrans ne divergent jamais.
  const visibleItems = [...filteredItems].sort(parGraviteEtFraicheur);
  const sansResume = visibleItems.filter((a) => !a.summary).length;
  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const toutesAlertes = comptesStatut[""];
  const filtreActif = status !== "" || severities.length > 0 || alertDate !== "" || groupId !== "";
  // Seuls les groupes qui ont des filiales méritent un filtre : pour une
  // organisation seule, la recherche par nom suffit.
  const entites = Object.values(entitiesById);
  const groupes = entites
    .filter((e) => entites.some((f) => f.parent_id === e.id))
    .sort((a, b) => a.name.localeCompare(b.name, "fr"));

  return (
    <AppLayout
      title="Alertes"
      searchPlaceholder="filtrer les alertes affichées"
      searchValue={search}
      onSearchChange={setSearch}
    >
      <div className="flex flex-col gap-3.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <div role="tablist" aria-label="Statut" className="flex gap-1 rounded-xl border border-line bg-panel p-1">
            {ONGLETS_STATUT.map((o) => {
              const actif = status === o.id;
              const n = comptesStatut[o.id];
              return (
                <button
                  key={o.id || "toutes"}
                  role="tab"
                  aria-selected={actif}
                  onClick={() => {
                    setOffset(0);
                    setStatus(o.id);
                  }}
                  className={`rounded-[9px] px-3 py-1.5 text-12 font-semibold transition-colors ${
                    actif ? "bg-panel-raised text-ink" : "text-ink-dim hover:text-ink"
                  }`}
                >
                  {o.label}
                  {n !== undefined && <span className="ml-1 font-mono-data tabular-nums opacity-80">· {n}</span>}
                </button>
              );
            })}
          </div>

          {/* Aucune puce enfoncée = toutes les gravités. Le compte de chaque
              puce suit le statut et la journée choisis. */}
          <div className="flex flex-wrap gap-1.5">
            {GRAVITES.map((g) => {
              const actif = severities.includes(g);
              return (
                <button
                  key={g}
                  onClick={() => toggleSeverity(g)}
                  aria-pressed={actif}
                  className={`rounded-md border px-2.5 py-[5px] font-mono-data text-11 transition-shadow ${severityPuce[g]} ${
                    actif ? "shadow-[inset_0_0_0_1px_currentColor]" : "opacity-80 hover:opacity-100"
                  }`}
                >
                  {severityLabels[g].toLowerCase()} {comptesGravite[g] ?? "…"}
                </button>
              );
            })}
          </div>

          {/* Journées RÉELLEMENT peuplées : un calendrier libre ferait tomber
              sur des jours vides sans prévenir. */}
          <select
            value={alertDate}
            onChange={(e) => {
              setOffset(0);
              setAlertDate(e.target.value);
            }}
            aria-label="Journée"
            className="rounded-[10px] border border-line bg-panel px-2.5 py-1.5 font-mono-data text-11 text-ink-dim outline-none focus:border-signal/60"
          >
            <option value="">toutes les journées</option>
            {availableDates.map((d) => (
              <option key={d} value={d}>
                journée · {jour(d)}
              </option>
            ))}
          </select>

          {(groupes.length > 0 || groupId) && (
            <select
              value={groupId}
              onChange={(e) => choisirGroupe(e.target.value)}
              aria-label="Groupe"
              className="rounded-[10px] border border-line bg-panel px-2.5 py-1.5 font-mono-data text-11 text-ink-dim outline-none focus:border-signal/60"
            >
              <option value="">tous les groupes</option>
              {groupes.map((g) => (
                <option key={g.id} value={g.id}>
                  groupe · {g.name} et filiales
                </option>
              ))}
              {groupId && !groupes.some((g) => g.id === groupId) && (
                <option value={groupId}>groupe · {entitiesById[groupId]?.name ?? "…"}</option>
              )}
            </select>
          )}

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <button
              onClick={() => void handleGenerate()}
              disabled={generating}
              // ⚠️ Bouton SECONDAIRE : la génération tourne seule chaque heure.
              // En vert plein, c'était le geste le plus visible de la page de
              // l'analyste alors que son travail est de TRAITER les alertes.
              title="La génération tourne automatiquement chaque heure. Ce bouton la relance tout de suite (détections des 7 derniers jours)."
              className="flex items-center gap-1.5 rounded-[10px] border border-line bg-panel-raised px-3 py-[7px] text-12 text-ink transition-colors hover:border-signal/40 disabled:opacity-50"
            >
              {generating && <Icon name="progress_activity" className="animate-spin text-14" />}
              {generating ? "Génération…" : "Relancer la génération"}
            </button>
            <BoutonExport chemin="/api/exports/alerts.csv" nom="alertes.csv" />
            {/* ⚠️ GENERER reste ouvert a l'analyste (routeur alertes), VIDER non
                (PEUT_ADMINISTRER). Et vider n'est pas reversible par une simple
                regeneration : la fenetre glissante de 7 jours laisse les
                incidents plus anciens hors de portee. */}
            {admin && (
              <button
                onClick={() => setShowDeleteAll(true)}
                disabled={!toutesAlertes}
                className="rounded-[10px] border border-critical/40 px-3 py-[7px] text-12 text-critical transition-colors hover:bg-critical/10 disabled:opacity-40"
              >
                Tout supprimer
              </button>
            )}
          </div>
        </div>

        {generateError && <p className="text-body-sm text-critical">{generateError}</p>}
        {deleteAllSummary && (
          <p className="rounded-xl border border-signal/30 bg-signal/[0.08] p-3 text-body-sm text-ink">
            {deleteAllSummary.deleted_count.toLocaleString("fr-FR")} alerte(s) supprimée(s).
          </p>
        )}
        {loadError && (
          <p className="rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
            Impossible de charger les alertes : {loadError}
          </p>
        )}

        <section className="pulse-panel p-4">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="font-mono-label text-10 uppercase tracking-[0.16em] text-signal">
              Synthèse IA
            </span>
            {digest ? (
              // ⚠️ Le périmètre est affiché AVEC le texte : un résumé dont on
              // ignore l'assiette n'est pas vérifiable.
              <span className="ml-auto font-mono-label text-10 text-ink-faint">
                {digest.model} · sur {digest.alert_count} alerte(s) · {digest.scope}
              </span>
            ) : (
              <button
                onClick={() => void handleDigest()}
                disabled={digestLoading || total === 0}
                className="ml-auto rounded-md border border-signal/30 bg-signal/10 px-2.5 py-1 font-mono-label text-11 text-signal transition-colors hover:bg-signal/20 disabled:opacity-40"
              >
                {digestLoading ? "rédaction…" : "résumer le périmètre affiché"}
              </button>
            )}
          </div>
          {digestError && <p className="mt-2 text-body-sm text-critical">{digestError}</p>}
          <p className="mt-2.5 max-w-[80ch] whitespace-pre-wrap text-body-sm text-ink">
            {digest
              ? digest.digest
              : "Ce qui s'est passé globalement, sur le périmètre filtré ci-dessus — statut, gravité et journée compris."}
          </p>
          {digest && (
            <button
              onClick={() => void handleDigest()}
              disabled={digestLoading}
              className="mt-2 font-mono-label text-11 text-signal disabled:opacity-40"
            >
              {digestLoading ? "rédaction…" : "rédiger à nouveau sur le filtre actuel"}
            </button>
          )}
        </section>

        {!loading && total === 0 && !loadError ? (
          <div className="flex flex-col items-center gap-2 rounded-[18px] border border-signal/[0.14] bg-panel px-8 py-12 text-center">
            <p className="font-display text-19 font-bold text-ink">
              {filtreActif && toutesAlertes ? "Aucune alerte pour ce filtre" : "Aucune alerte"}
            </p>
            <p className="max-w-xl text-body-sm text-ink-dim">
              {filtreActif && toutesAlertes
                ? `${toutesAlertes} alerte(s) existent, mais aucune ne satisfait le filtre.`
                : "Aucune détection récente ne correspond aux organisations surveillées."}
            </p>
            {filtreActif && toutesAlertes ? (
              <button
                onClick={reinitialiser}
                className="mt-2 rounded-[10px] border border-line bg-panel-raised px-3.5 py-2 text-body-sm text-ink"
              >
                Réinitialiser les filtres
              </button>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {sansResume > 0 && (
              // ⚠️ Dire l'état UNE fois plutôt que le répéter à chaque ligne.
              <p className="font-mono-label text-11 text-ink-faint">
                {sansResume} alerte(s) sans résumé sur {visibleItems.length}
              </p>
            )}
            {visibleItems.length > 0 && <EnteteListeAlertes />}
            {visibleItems.map((a) => (
              <LigneAlerte key={a.id} alerte={a} entitiesById={entitiesById} />
            ))}
            {loading && items.length === 0 && (
              <p className="text-body-sm text-ink-dim">Chargement des alertes…</p>
            )}
          </div>
        )}

        {total > 0 && (
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono-label text-11 text-ink-faint">
              {visibleItems.length} ligne(s) affichée(s) sur {total} correspondant au filtre · page{" "}
              {page} / {totalPages}
            </span>
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim transition-colors hover:text-ink disabled:opacity-40"
              >
                Précédent
              </button>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim transition-colors hover:text-ink disabled:opacity-40"
              >
                Suivant
              </button>
            </div>
          </div>
        )}
      </div>

      {showDeleteAll && (
        <DeleteAllAlertsConfirmModal
          total={toutesAlertes ?? total}
          onCancel={() => setShowDeleteAll(false)}
          onConfirm={handleDeleteAll}
        />
      )}
    </AppLayout>
  );
}
