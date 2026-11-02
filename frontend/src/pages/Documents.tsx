import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  documentsApi,
  type AnnouncementClass,
  type DeleteAllResponse,
  type DocumentListItem,
  type DocumentSortBy,
  type SortOrder,
} from "../api/documents";
import { sourcesApi, type SourceApi } from "../api/sources";
import { AppLayout } from "../components/layout/AppLayout";
import { DocumentDetailPanel } from "../components/documents/DocumentDetailPanel";
import { Icon } from "../components/ui/Icon";
import { useAuth } from "../context/auth-context";
import { peutAdministrer } from "../lib/roles";
import { useRequete } from "../hooks/useRequete";
import { DeleteAllConfirmModal } from "../components/documents/ConfirmationSuppressionDocuments";
import { LigneDocument } from "../components/documents/LigneDocument";

const PAGE_SIZE = 25;

// Noms des collecteurs actuels (voir backend/app/pipeline/collect/*/adapter.py,
// COLLECTOR_NAME) -- pas d'endpoint dédié pour les lister, la liste est courte
// et stable, autant l'inline ici plutôt qu'ajouter un aller-retour réseau.
const COLLECTORS = [
  "cyberscraper",
  "akira",
  "xssf",
  "xenforo_latest",
  "breachforums_guest",
  "mybb_latest",
  "exilio404",
  "doxbyte",
];

const SORT_OPTIONS: { value: DocumentSortBy; label: string }[] = [
  { value: "freshness", label: "Plus récents d'abord" },
  { value: "relevance", label: "Pertinence (watchlist)" },
  { value: "fetched_at", label: "Date de collecte" },
  { value: "published_at", label: "Date de publication" },
  { value: "title", label: "Titre" },
];

type OngletClasse = "retenus" | "uncertain" | "leak" | "noise" | "tous";

// Onglets de classement. « Retenus » (fuites + incertains) reste le défaut :
// c'est la vue qu'avait déjà l'analyste — le bruit écarté mais jamais caché,
// son compte étant affiché sur son propre onglet.
const ONGLETS: { id: OngletClasse; label: string }[] = [
  { id: "retenus", label: "Retenus" },
  { id: "uncertain", label: "Incertains" },
  { id: "leak", label: "Fuites" },
  { id: "noise", label: "Bruit" },
  { id: "tous", label: "Tous" },
];

const CLASSES_ONGLET: Record<OngletClasse, AnnouncementClass[] | undefined> = {
  retenus: ["leak", "uncertain"],
  uncertain: ["uncertain"],
  leak: ["leak"],
  noise: ["noise"],
  tous: undefined,
};




export function Documents() {
  const [offset, setOffset] = useState(0);

  const [sourceId, setSourceId] = useState("");
  const [collector, setCollector] = useState("");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [onlyMatched, setOnlyMatched] = useState(false);
  // Le bruit est ecarte PAR DEFAUT mais jamais masque en silence : le
  // nombre de documents ecartes est affiche, avec un bouton pour les
  // montrer. `uncertain` reste toujours visible -- c'est ce que les regles
  // n'ont pas su trancher, le confondre avec le bruit perdrait des victimes.
  const [classe, setClasse] = useState<OngletClasse>("retenus");
  // Defaut = fraicheur reelle (published_at sinon fetched_at) : trier sur
  // la seule date de collecte remontait des victimes de 2023 en tete,
  // toute une passe partageant la meme seconde de fetched_at.
  const [sortBy, setSortBy] = useState<DocumentSortBy>("freshness");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [fetchedFrom, setFetchedFrom] = useState("");
  const [fetchedTo, setFetchedTo] = useState("");

  // Document ouvert, porte par l'URL (`?doc=<id>`) et non par un simple etat
  // local : c'est ce qui rend un document ADRESSABLE. La page Alertes en a
  // besoin pour renvoyer l'analyste vers la piece justificative, et le lien
  // devient partageable entre analystes.
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("doc");
  const setSelectedId = (id: string | null) => {
    setSearchParams(
      (params) => {
        if (id) params.set("doc", id);
        else params.delete("doc");
        return params;
      },
      { replace: true },
    );
  };
  const [showDeleteAll, setShowDeleteAll] = useState(false);
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);
  const [deleteAllSummary, setDeleteAllSummary] = useState<DeleteAllResponse | null>(null);

  const sourcesReq = useRequete(() => sourcesApi.list(), []);
  const sources: SourceApi[] = sourcesReq.donnees ?? [];

  // Une réponse périmée (filtre changé entre-temps) est ignorée ; la liste
  // précédente reste affichée, signalée « en chargement ».
  const listeReq = useRequete(
    () =>
      documentsApi.list({
        source_id: sourceId || undefined,
        collector: collector || undefined,
        q: search || undefined,
        only_matched: onlyMatched || undefined,
        announcement_class: CLASSES_ONGLET[classe],
        fetched_from: fetchedFrom || undefined,
        fetched_to: fetchedTo || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        offset,
        limit: PAGE_SIZE,
      }),
    [sourceId, collector, search, onlyMatched, classe, fetchedFrom, fetchedTo, sortBy, sortOrder, offset],
  );
  // Après « tout supprimer », la liste se vide immédiatement.
  const vide = deleteAllSummary !== null && listeReq.chargement;
  const items: DocumentListItem[] = vide ? [] : (listeReq.donnees?.items ?? []);
  const total = vide ? 0 : (listeReq.donnees?.total ?? 0);
  const loading = listeReq.chargement;
  const [erreurAction, setLoadError] = useState<string | null>(null);
  const loadError = listeReq.erreur ?? erreurAction;

  // ⚠️ Les compteurs d'onglets portent sur les MÊMES filtres que la liste
  // (source, collecteur, recherche, dates) : un onglet qui annoncerait 46
  // incertains au-dessus d'une liste filtrée qui n'en montre que 3 mentirait.
  const comptesReq = useRequete(async () => {
    const base = {
      source_id: sourceId || undefined,
      collector: collector || undefined,
      q: search || undefined,
      only_matched: onlyMatched || undefined,
      fetched_from: fetchedFrom || undefined,
      fetched_to: fetchedTo || undefined,
      limit: 1,
    };
    const paires = await Promise.all(
      ONGLETS.map((o) =>
        documentsApi
          .list({ ...base, announcement_class: CLASSES_ONGLET[o.id] })
          .then((r) => [o.id, r.total] as const),
      ),
    );
    return Object.fromEntries(paires);
  }, [sourceId, collector, search, onlyMatched, fetchedFrom, fetchedTo]);
  const comptes: Partial<Record<OngletClasse, number>> = comptesReq.donnees ?? {};

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    setOffset(0);
    setSearch(searchInput.trim());
  }

  async function handleDeleteAll() {
    // ⚠️ Une erreur non captée ici DISPARAIT : la promesse est rejetée, rien
    // n'est affiché, et l'analyste conclut que son clic n'a rien fait alors
    // que l'opération a échoué. Le silence est le pire retour possible.
    try {
      const result = await documentsApi.deleteAll();
      setShowDeleteAll(false);
      setOffset(0);
      setDeleteAllSummary(result);
      listeReq.recharger();
      comptesReq.recharger();
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Suppression impossible");
    }
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <AppLayout title="Documents collectés" searchPlaceholder="Rechercher un document...">
      <section className="pulse-panel stagger-in mb-6 flex flex-wrap items-end justify-between gap-4 p-4">
        <div>
          <span className="text-10 font-bold uppercase tracking-tighter text-on-surface-variant opacity-70">
            Documents en base
          </span>
          <p className="font-mono-data text-headline-lg tabular-nums text-signal">{total.toLocaleString("fr-FR")}</p>
        </div>

        {admin && (
          <button
            onClick={() => setShowDeleteAll(true)}
            disabled={total === 0}
            title="Supprimer tous les documents collectes"
            className="flex items-center gap-1.5 rounded border border-error/40 bg-error-container/10 px-3 py-1.5 text-body-sm text-error transition-all hover:bg-error-container/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name="delete_forever" className="text-16" />
            Vider la base de collecte
          </button>
        )}

        <form onSubmit={handleSearchSubmit} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">Source</label>
            <select
              value={sourceId}
              onChange={(e) => {
                setOffset(0);
                setSourceId(e.target.value);
              }}
              className="rounded border border-outline-variant bg-background px-3 py-1.5 text-body-sm outline-none focus:border-primary"
            >
              <option value="">Toutes</option>
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">Collecteur</label>
            <select
              value={collector}
              onChange={(e) => {
                setOffset(0);
                setCollector(e.target.value);
              }}
              className="rounded border border-outline-variant bg-background px-3 py-1.5 text-body-sm outline-none focus:border-primary"
            >
              <option value="">Tous</option>
              {COLLECTORS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">
              Recherche (titre/contenu)
            </label>
            <div className="flex gap-2">
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="ex: database, RDP..."
                className="w-56 rounded border border-outline-variant bg-background px-3 py-1.5 font-mono-data text-mono-data outline-none focus:border-primary"
              />
              <button
                type="submit"
                className="rounded-lg bg-primary px-4 py-1.5 text-body-sm font-bold text-on-primary transition-all hover:opacity-90"
              >
                <Icon name="search" className="text-18" />
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">Trier par</label>
            <div className="flex gap-1">
              <select
                value={sortBy}
                onChange={(e) => {
                  setOffset(0);
                  setSortBy(e.target.value as DocumentSortBy);
                }}
                className="rounded border border-outline-variant bg-background px-3 py-1.5 text-body-sm outline-none focus:border-primary"
              >
                {SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => {
                  setOffset(0);
                  setSortOrder(sortOrder === "asc" ? "desc" : "asc");
                }}
                disabled={sortBy === "relevance"}
                title={sortOrder === "asc" ? "Croissant" : "Décroissant"}
                className="rounded border border-outline-variant bg-background px-2 py-1.5 text-on-surface-variant transition-all hover:bg-surface-bright disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Icon name={sortOrder === "asc" ? "arrow_upward" : "arrow_downward"} className="text-16" />
              </button>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">Collecté depuis</label>
            <input
              type="datetime-local"
              value={fetchedFrom}
              onChange={(e) => {
                setOffset(0);
                setFetchedFrom(e.target.value);
              }}
              className="rounded border border-outline-variant bg-background px-3 py-1.5 font-mono-data text-13 outline-none focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="font-caption text-caption uppercase text-on-surface-variant">Collecté jusqu'à</label>
            <input
              type="datetime-local"
              value={fetchedTo}
              onChange={(e) => {
                setOffset(0);
                setFetchedTo(e.target.value);
              }}
              className="rounded border border-outline-variant bg-background px-3 py-1.5 font-mono-data text-13 outline-none focus:border-primary"
            />
          </div>
          <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-body-sm text-on-surface-variant">
            <input
              type="checkbox"
              checked={onlyMatched}
              onChange={(e) => {
                setOffset(0);
                setOnlyMatched(e.target.checked);
              }}
              className="h-4 w-4 accent-tertiary"
            />
            Watchlist uniquement
          </label>
        </form>
      </section>

      {/* ⚠️ « Incertain » n'est PAS un demi-bruit : c'est ce que les règles
          n'ont pas su trancher. Ces documents restent dans la détection et
          peuvent produire une alerte — ne jamais les présenter comme écartés. */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div
          role="tablist"
          aria-label="Classement des annonces"
          className="flex gap-1 rounded-xl border border-line bg-panel p-1"
        >
          {ONGLETS.map((o) => {
            const actif = classe === o.id;
            const n = comptes[o.id];
            return (
              <button
                key={o.id}
                role="tab"
                aria-selected={actif}
                onClick={() => {
                  setOffset(0);
                  setClasse(o.id);
                }}
                className={`rounded-[9px] px-3 py-1.5 text-12 font-semibold transition-colors ${
                  actif
                    ? `bg-panel-raised ${o.id === "uncertain" ? "text-info" : "text-ink"}`
                    : "text-ink-dim hover:text-ink"
                }`}
              >
                {o.label}
                {n !== undefined && (
                  <span className="ml-1.5 font-mono-data tabular-nums opacity-80">
                    · {n.toLocaleString("fr-FR")}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <p className="font-mono-label text-11 text-ink-dim">
          incertain = ce que les règles n&apos;ont pas su trancher — ces documents restent dans la
          détection
        </p>
      </div>

      {loadError && (
        <p className="mb-4 rounded border border-error/40 bg-error-container/20 p-3 text-body-sm text-error">
          Impossible de charger les documents : {loadError}
        </p>
      )}

      {deleteAllSummary && (
        <div className="mb-4 flex items-center justify-between rounded border border-tertiary/40 bg-tertiary-container/20 p-3 text-body-sm text-tertiary">
          <span>
            Base de collecte videe : <strong>{deleteAllSummary.deleted_count.toLocaleString("fr-FR")}</strong>{" "}
            document(s) et <strong>{deleteAllSummary.deleted_detections_count.toLocaleString("fr-FR")}</strong>{" "}
            détection(s) associée(s) supprimés.
          </span>
          <button onClick={() => setDeleteAllSummary(null)} className="text-tertiary hover:opacity-70">
            <Icon name="close" className="text-16" />
          </button>
        </div>
      )}

      <div className="pulse-panel stagger-in overflow-hidden" style={{ animationDelay: "100ms" }}>
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b border-outline-variant bg-surface-container-high">
              <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Titre</th>
              <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Source</th>
              <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Collecteur</th>
              <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Auteur</th>
              <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Publié</th>
              <th className="px-4 py-3 font-caption text-caption uppercase text-on-surface-variant">Collecté</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-outline-variant/30">
            {!loading && items.length === 0 && !loadError && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-on-surface-variant">
                  Aucun document ne correspond aux filtres.
                </td>
              </tr>
            )}
            {items.map((doc) => (
              <LigneDocument key={doc.id} doc={doc} onOuvrir={setSelectedId} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex items-center justify-between text-body-sm text-on-surface-variant">
        <span>
          Page {page} / {totalPages} ({total.toLocaleString("fr-FR")} documents)
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="rounded border border-outline-variant px-3 py-1.5 transition-all hover:bg-surface-bright disabled:opacity-40"
          >
            Précédent
          </button>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="rounded border border-outline-variant px-3 py-1.5 transition-all hover:bg-surface-bright disabled:opacity-40"
          >
            Suivant
          </button>
        </div>
      </div>

      {selectedId && <DocumentDetailPanel documentId={selectedId} onClose={() => setSelectedId(null)} />}

      {showDeleteAll && (
        <DeleteAllConfirmModal total={total} onCancel={() => setShowDeleteAll(false)} onConfirm={handleDeleteAll} />
      )}
    </AppLayout>
  );
}
