import { useState } from "react";
import {
  detectionsApi,
  type DetectionListItem,
  type DetectionSortBy,
  type IntelXDetectionCorroboration,
  type SortOrder,
} from "../api/detections";
import { AppLayout } from "../components/layout/AppLayout";
import { DocumentDetailPanel } from "../components/documents/DocumentDetailPanel";
import { Icon } from "../components/ui/Icon";
import { MaskedValue } from "../components/ui/MaskedValue";
import { ageRelatif } from "../lib/alertes";
import { detectionTypeLabels } from "../lib/taxonomy";
import { dateHeure } from "../lib/format";
import { useRequete } from "../hooks/useRequete";

const PAGE_SIZE = 25;

const SORT_OPTIONS: { value: DetectionSortBy; label: string }[] = [
  { value: "created_at", label: "Date de détection" },
  { value: "type", label: "Type" },
  { value: "value_masked", label: "Valeur (masquée)" },
];

// Types de detection actuellement geres par backend/app/pipeline/detect/registry.py.
// Miroir de DetectionType (backend/app/contracts/detection.py) -- doit rester
// aligné, sinon les nouveaux types ne sont pas proposés au filtrage.
const DETECTION_TYPES = [
  "email",
  "card",
  "iban",
  "crypto_wallet",
  "api_key",
  "credentials",
  "phone",
  "domain",
  "volume",
  "organization",
  "distribution_channel",
  "source_topic",
  "announcement",
  "threat_actor",
];

// Rubriques de presse / revue d'actualité : le contenu y parle de fuites sans
// en être une. Les détections qui en proviennent sont techniquement correctes
// mais rarement actionnables — signalées pour être distinguées au premier coup
// d'œil. Voir backend/app/pipeline/detect/patterns/topic.py.
const PRESS_TOPIC_HINTS = ["news", "сми", "media", "presse", "article"];

function isPressTopic(topic: string): boolean {
  const normalized = topic.toLowerCase();
  return PRESS_TOPIC_HINTS.some((hint) => normalized.includes(hint));
}

function typeLabel(type: string): string {
  return detectionTypeLabels[type as keyof typeof detectionTypeLabels] ?? type.replace("_", " ");
}

const CHAMP =
  "rounded-lg border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink outline-none transition-colors focus:border-signal/60";

export function Detections() {
  // ⚠️ La page n'avait AUCUN filtre par valeur : « cette organisation est-elle
  // déjà apparue ? » n'avait pas de réponse ici.
  const [recherche, setRecherche] = useState("");
  const [offset, setOffset] = useState(0);

  const [type, setType] = useState("");
  const [validated, setValidated] = useState("");
  const [relevance, setRelevance] = useState("");
  const [sortBy, setSortBy] = useState<DetectionSortBy>("created_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);

  const [corroboratingId, setCorroboratingId] = useState<string | null>(null);
  const [corroborationResults, setCorroborationResults] = useState<
    Record<string, IntelXDetectionCorroboration>
  >({});
  const [corroborationErrors, setCorroborationErrors] = useState<Record<string, string>>({});

  async function handleCorroborateIntelx(detectionId: string) {
    setCorroboratingId(detectionId);
    setCorroborationErrors((prev) => ({ ...prev, [detectionId]: "" }));
    try {
      const result = await detectionsApi.corroborateIntelx(detectionId);
      setCorroborationResults((prev) => ({ ...prev, [detectionId]: result }));
    } catch (err) {
      setCorroborationErrors((prev) => ({
        ...prev,
        [detectionId]: err instanceof Error ? err.message : "Erreur inconnue",
      }));
    } finally {
      setCorroboratingId(null);
    }
  }

  // Une seule réponse retenue : celle des filtres AFFICHÉS. Avant, deux
  // changements de filtre rapides lançaient deux requêtes et la plus lente
  // l'emportait, laissant une liste qui ne correspondait plus au filtre.
  const requete = useRequete(
    () =>
      detectionsApi.list({
        type: type || undefined,
        validated: validated === "" ? undefined : validated === "true",
        isRelevant: relevance === "" ? undefined : relevance === "true",
        createdFrom: createdFrom || undefined,
        createdTo: createdTo || undefined,
        q: recherche.trim() || undefined,
        sortBy,
        sortOrder,
        offset,
        limit: PAGE_SIZE,
      }),
    [type, validated, relevance, createdFrom, createdTo, recherche.trim(), sortBy, sortOrder, offset],
  );
  const items: DetectionListItem[] = requete.donnees?.items ?? [];
  const total = requete.donnees?.total ?? 0;
  const countsByType: Record<string, number> = requete.donnees?.counts_by_type ?? {};
  const relevantCount = requete.donnees?.relevant_count ?? 0;
  const loading = requete.chargement;
  const loadError = requete.erreur;

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const totalDetections = Object.values(countsByType).reduce((sum, n) => sum + n, 0);
  // Pastilles de type : seulement celles qui ont des détections (plus le type
  // filtré) — quatorze pastilles dont la moitié à zéro noyaient les autres.
  const typesVisibles = DETECTION_TYPES.filter((t) => (countsByType[t] ?? 0) > 0 || t === type);

  return (
    <AppLayout
      title="Détections"
      searchPlaceholder="Rechercher une valeur (domaine, adresse…)"
      searchValue={recherche}
      onSearchChange={setRecherche}
    >
      <div className="mb-3.5 flex flex-col gap-3.5 xl:flex-row">
        <section className="flex flex-1 flex-wrap items-center gap-x-4 gap-y-3 rounded-[18px] border border-line bg-panel px-4 py-3.5">
          <span className="font-mono-data text-28 tabular-nums text-ink">
            {totalDetections.toLocaleString("fr-FR")}
          </span>
          <p className="text-body-sm leading-tight text-ink-dim">
            détections en base
            <br />
            {type ? `filtre : ${typeLabel(type)}` : "tous types confondus"}
          </p>
          <div className="ml-auto flex flex-wrap gap-1.5">
            {typesVisibles.map((t) => {
              const actif = type === t;
              return (
                <button
                  key={t}
                  onClick={() => {
                    setOffset(0);
                    setType(actif ? "" : t);
                  }}
                  aria-pressed={actif}
                  className={`rounded-md border px-2.5 py-1 font-mono-data text-11 transition-colors ${
                    actif
                      ? "border-signal/40 bg-signal/10 text-signal"
                      : "border-line bg-panel-sunken text-ink-dim hover:text-ink"
                  }`}
                >
                  {typeLabel(t)}{" "}
                  <span className="tabular-nums opacity-70">
                    {(countsByType[t] ?? 0).toLocaleString("fr-FR")}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        {/* ⚠️ La maquette affichait ici les détections « non rattachées » à une
            organisation. L'API ne sait pas les compter : on montre ce qu'elle
            sait, les détections dont le document contient un terme de la
            watchlist — en le disant, pour qu'on ne lise pas l'un pour l'autre. */}
        <section className="flex items-center gap-3.5 rounded-[18px] border border-signal/25 bg-panel px-4 py-3.5 xl:w-80">
          <span className="font-mono-data text-28 tabular-nums text-signal">
            {relevantCount.toLocaleString("fr-FR")}
          </span>
          <p className="text-body-sm leading-tight text-ink-dim">
            <span className="text-signal">pertinentes</span> (watchlist)
            <br />
            le document source contient un terme surveillé
          </p>
        </section>
      </div>

      <div className="mb-3.5 flex flex-wrap items-end gap-3 rounded-xl border border-line bg-panel px-4 py-3">
        <label className="flex flex-col gap-1">
          <span className="font-caption text-caption text-ink-faint">Vérification</span>
          <select
            value={validated}
            onChange={(e) => {
              setOffset(0);
              setValidated(e.target.value);
            }}
            className={CHAMP}
          >
            <option value="">Toutes</option>
            <option value="true">Validées (checksum)</option>
            <option value="false">Motif seul</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-caption text-caption text-ink-faint">Pertinence</span>
          <select
            value={relevance}
            onChange={(e) => {
              setOffset(0);
              setRelevance(e.target.value);
            }}
            className={CHAMP}
          >
            <option value="">Toutes</option>
            <option value="true">Pertinentes (watchlist)</option>
            <option value="false">Hors watchlist</option>
          </select>
        </label>
        <div className="flex flex-col gap-1">
          <span className="font-caption text-caption text-ink-faint">Trier par</span>
          <div className="flex gap-1">
            <select
              value={sortBy}
              onChange={(e) => {
                setOffset(0);
                setSortBy(e.target.value as DetectionSortBy);
              }}
              className={CHAMP}
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
              title={sortOrder === "asc" ? "Croissant" : "Décroissant"}
              className="rounded-lg border border-line bg-panel-sunken px-2 py-1.5 text-ink-dim transition-colors hover:text-ink"
            >
              <Icon name={sortOrder === "asc" ? "arrow_upward" : "arrow_downward"} className="text-16" />
            </button>
          </div>
        </div>
        <label className="flex flex-col gap-1">
          <span className="font-caption text-caption text-ink-faint">Détectée depuis</span>
          <input
            type="datetime-local"
            value={createdFrom}
            onChange={(e) => {
              setOffset(0);
              setCreatedFrom(e.target.value);
            }}
            className={`${CHAMP} font-mono-data text-12`}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-caption text-caption text-ink-faint">Jusqu&apos;à</span>
          <input
            type="datetime-local"
            value={createdTo}
            onChange={(e) => {
              setOffset(0);
              setCreatedTo(e.target.value);
            }}
            className={`${CHAMP} font-mono-data text-12`}
          />
        </label>
      </div>

      {loadError && (
        <p className="mb-4 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger les détections : {loadError}
        </p>
      )}

      <div className="overflow-hidden rounded-[18px] border border-line bg-panel">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] border-collapse text-left">
            <thead>
              <tr className="border-b border-line">
                {["Type", "Valeur (masquée)", "Document source", "Collecteur", "Vérification", "Vu", ""].map(
                  (h) => (
                    <th
                      key={h}
                      className="px-4 py-2.5 font-mono-label text-10 font-medium uppercase tracking-[0.12em] text-ink-faint"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-body-sm text-ink-dim">
                    Chargement des détections…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && !loadError && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-body-sm text-ink-dim">
                    Aucune détection ne correspond aux filtres.
                  </td>
                </tr>
              )}
              {items.map((d) => (
                <tr
                  key={d.id}
                  className="border-b border-line-soft transition-colors last:border-b-0 hover:bg-panel-raised/40"
                >
                  <td className="px-4 py-2.5 font-mono-data text-11 text-ink-dim">{typeLabel(d.type)}</td>
                  <td className="max-w-[240px] truncate px-4 py-2.5">
                    <MaskedValue value={d.value_masked} />
                  </td>
                  <td className="max-w-xs px-4 py-2.5">
                    {/* ⚠️ Plus de lien direct vers l'URL d'origine : c'est
                        presque toujours un `.onion`, qui exige Tor — un lien
                        ordinaire ne mène nulle part. Le document s'ouvre dans
                        l'application, où l'URL est affichée sans être cliquable. */}
                    <button
                      onClick={() => setSelectedDocumentId(d.document_id)}
                      title="Voir le document dans l'application"
                      className="block max-w-full truncate text-left text-body-sm text-ink transition-colors hover:text-signal"
                    >
                      {d.document_title || "(sans titre)"}
                    </button>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap items-center gap-1">
                      <span className="font-mono-data text-11 text-ink-dim">
                        {d.document_collector ?? "—"}
                      </span>
                      {d.document_topic && (
                        <span
                          title={`Rubrique déclarée par la source : ${d.document_topic}`}
                          className={`rounded border px-1.5 py-0.5 font-mono-data text-10 ${
                            isPressTopic(d.document_topic)
                              ? "border-warn/40 bg-warn-dim/40 text-warn"
                              : "border-line text-ink-dim"
                          }`}
                        >
                          {d.document_topic}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {/* « Validée » = checksum vérifié (Luhn, mod-97), jamais
                          « fait confirmé ». Sans checksum : « motif seul ». */}
                      <span
                        title={
                          d.validated
                            ? "Confirmée par un validateur (Luhn, mod-97…)"
                            : "Motif seul, pas de checksum pour ce type"
                        }
                        className={`font-mono-data text-11 ${d.validated ? "text-ok" : "text-ink-faint"}`}
                      >
                        {d.validated ? "validée" : "motif seul"}
                      </span>
                      {d.is_relevant && (
                        <span
                          title="Le document source contient un terme de la watchlist"
                          className="rounded border border-signal/35 bg-signal/10 px-1.5 font-mono-label text-10 text-signal"
                        >
                          watchlist
                        </span>
                      )}
                      {d.corroboration_status === "corroborated" && (
                        <span
                          title={`Annonce indexée aussi par RansomLook, ${
                            d.corroboration_match === "name"
                              ? "rapprochée par raison sociale dans l'historique du gang"
                              : "rapprochée par domaine"
                          }${
                            (d.corroborated_groups ?? []).length > 1
                              ? ` — revendiquée par : ${(d.corroborated_groups ?? []).join(", ")}`
                              : ""
                          }`}
                          className="rounded border border-ok/35 bg-ok/10 px-1.5 font-mono-label text-10 text-ok"
                        >
                          confirmée · {d.corroborated_group}
                          {(d.corroborated_groups ?? []).length > 1
                            ? ` +${(d.corroborated_groups ?? []).length - 1}`
                            : ""}
                        </span>
                      )}
                      {d.corroboration_status === "exclusive" && (
                        <span
                          title="Absente de tout l'historique du gang chez RansomLook — ce n'est pas un doute, nous lisons le site à la source"
                          className="font-mono-label text-10 text-ink-faint"
                        >
                          vue par nous seuls
                        </span>
                      )}
                    </div>
                  </td>
                  <td
                    className="whitespace-nowrap px-4 py-2.5 text-right font-mono-data text-11 text-ink-faint"
                    title={dateHeure(d.created_at)}
                  >
                    {ageRelatif(d.created_at)}
                  </td>
                  <td className="px-4 py-2.5">
                    {d.type === "domain" && (
                      <div className="flex flex-col gap-1">
                        <button
                          onClick={() => void handleCorroborateIntelx(d.id)}
                          disabled={corroboratingId === d.id}
                          title="Corroborer via IntelX (quota limité, à utiliser avec parcimonie)"
                          className="w-fit rounded border border-line px-1.5 py-0.5 font-mono-data text-10 text-ink-dim transition-colors hover:border-signal/35 hover:text-signal disabled:opacity-50"
                        >
                          {corroboratingId === d.id ? "IntelX…" : "IntelX"}
                        </button>
                        {corroborationErrors[d.id] && (
                          <span className="max-w-[160px] text-10 text-critical">
                            {corroborationErrors[d.id]}
                          </span>
                        )}
                        {corroborationResults[d.id] && (
                          <span className="max-w-[160px] text-10 text-ink-dim">
                            {/* Compteur saturé au plafond IntelX : lire « au moins N ». */}
                            {corroborationResults[d.id].is_truncated
                              ? `au moins ${corroborationResults[d.id].hit_count}`
                              : corroborationResults[d.id].hit_count}{" "}
                            résultat(s)
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5">
          <span className="font-mono-label text-11 text-ink-faint">
            {items.length} lignes sur {total.toLocaleString("fr-FR")} · page {page} / {totalPages}
          </span>
          <span className="font-mono-label text-11 text-ink-dim">
            aucune valeur complète n&apos;est stockée : le masquage est appliqué à l&apos;écriture
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
      </div>

      {selectedDocumentId && (
        <DocumentDetailPanel documentId={selectedDocumentId} onClose={() => setSelectedDocumentId(null)} />
      )}
    </AppLayout>
  );
}
