import { useState } from "react";
import {
  entitiesApi,
  type EntityApi,
  type OrganizationCandidate,
  type SelectorInput,
  type SelectorType,
} from "../../api/entities";
import { DocumentDetailPanel } from "../documents/DocumentDetailPanel";
import { FicheOrganisation } from "./FicheOrganisation";
import { CitationsCandidate } from "./CitationsCandidate";
import { invaliderBadges } from "../../hooks/useVeilleBadges";
import { useAuth } from "../../context/auth-context";
import { peutAdministrer } from "../../lib/roles";
import { Icon } from "../ui/Icon";
import { LectureSeule } from "../ui/LectureSeule";
import { jour } from "../../lib/format";
import { useRequete } from "../../hooks/useRequete";
import {
  useCandidats,
  useCorroborationIntelx,
  useDocumentsEntite,
  useSousDomaines,
} from "./useEntites";

const SELECTOR_LABELS: Record<SelectorType, string> = {
  domain: "domaine",
  email_domain: "domaine email",
  keyword: "raison sociale",
};

const CHAMP =
  "rounded-lg border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink outline-none transition-colors focus:border-signal/60 disabled:opacity-50";

function emptySelector(): SelectorInput {
  return { type: "domain", value: "" };
}

/**
 * Organisations surveillées : qui l'on surveille, et avec quels sélecteurs.
 * Générique par conception (CONTRIBUTING.md §1) : aucun nom d'organisation en dur.
 *
 * ⚠️ C'EST ICI QUE SE JOUE LA CAPACITÉ MÊME À ALERTER. Une organisation sans
 * sélecteur ne peut structurellement jamais produire d'alerte — le moteur n'a
 * rien à comparer. « Aucun sélecteur déclaré » se lisait comme un détail de
 * saisie ; le bandeau dit la conséquence, et « Corriger » mène droit à elles.
 */
export function EntitiesPanel() {
  // ⚠️ DECLARER, MODIFIER, ENRICHIR : tout est en PEUT_ADMINISTRER cote
  // serveur, y compris la decouverte de sous-domaines et la corroboration
  // IntelX (elles consomment un quota et sortent en clair). La LISTE et les
  // documents rattaches restent lisibles : c'est la verifiabilite.
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);
  const requete = useRequete(() => entitiesApi.list(), []);
  const entities: EntityApi[] = requete.donnees ?? [];
  const loadError = requete.erreur;
  const loaded = !requete.chargement;
  const modifierEntites = requete.modifier;
  const setEntities = (fn: (precedent: EntityApi[]) => EntityApi[]) =>
    modifierEntites((precedent) => fn(precedent ?? []));
  const [filtreAveugles, setFiltreAveugles] = useState(false);
  const secteurs = useRequete(() => entitiesApi.sectors(), []).donnees ?? [];
  const {
    candidates,
    displayedCandidates,
    candidatesError,
    backfillJob,
    backfillError,
    llmFiltering,
    llmFilterError,
    llmKeptNames,
    setLlmKeptNames,
    handleFilterWithLlm,
    handleStartBackfill,
  } = useCandidats();
  const {
    corroboratingId,
    corroborationError,
    corroborationResults,
    handleCorroborateIntelx,
  } = useCorroborationIntelx();
  const {
    expandedEntityId,
    entityDocuments,
    entityDocumentsTotal,
    loadingDocumentsId,
    documentsError,
    handleToggleDocuments,
  } = useDocumentsEntite();

  const [formOuvert, setFormOuvert] = useState(false);
  const [name, setName] = useState("");
  const [nouveauParent, setNouveauParent] = useState("");
  const [nouveauPays, setNouveauPays] = useState("");
  const [nouveauSecteur, setNouveauSecteur] = useState("");
  const [selectors, setSelectors] = useState<SelectorInput[]>([emptySelector()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ajout d'un sélecteur directement sur la carte — le geste qui « répare »
  // une organisation aveugle, sans rouvrir de formulaire.
  const [ajoutPour, setAjoutPour] = useState<string | null>(null);
  const [ajoutType, setAjoutType] = useState<SelectorType>("domain");
  const [ajoutValeur, setAjoutValeur] = useState("");
  const [ajoutEnCours, setAjoutEnCours] = useState(false);



  const [openDocumentId, setOpenDocumentId] = useState<string | null>(null);
  const [citationsDe, setCitationsDe] = useState<string | null>(null);




  function remplacer(updated: EntityApi) {
    setEntities((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
    // Le compteur « organisations aveugles » de la barre latérale suit.
    invaliderBadges();
  }
  const {
    discoveringId,
    discoveryError,
    discoveryResults,
    selectedSubdomains,
    addingSubdomains,
    handleDiscoverSubdomains,
    toggleSubdomainSelection,
    handleAddSelectedSubdomains,
  } = useSousDomaines(remplacer);


  function handleUseCandidate(candidate: OrganizationCandidate) {
    setName(candidate.name);
    setSelectors([{ type: "keyword", value: candidate.name }]);
    setFormOuvert(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function updateSelector(index: number, patch: Partial<SelectorInput>) {
    setSelectors((prev) => prev.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await entitiesApi.create({
        name: name.trim(),
        selectors: selectors.filter((s) => s.value.trim()),
        parent_id: nouveauParent || null,
        country: nouveauPays.trim() || null,
        sector: nouveauSecteur || null,
      });
      setEntities((prev) => [created, ...prev]);
      invaliderBadges();
      setName("");
      setNouveauParent("");
      setNouveauPays("");
      setNouveauSecteur("");
      setSelectors([emptySelector()]);
      setFormOuvert(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAjoutSelecteur(entity: EntityApi) {
    if (!ajoutValeur.trim()) return;
    setAjoutEnCours(true);
    setError(null);
    try {
      const existants: SelectorInput[] = entity.selectors.map((s) => ({ type: s.type, value: s.value }));
      remplacer(
        await entitiesApi.update(entity.id, {
          selectors: [...existants, { type: ajoutType, value: ajoutValeur.trim() }],
        }),
      );
      setAjoutPour(null);
      setAjoutValeur("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ajout du sélecteur impossible");
    } finally {
      setAjoutEnCours(false);
    }
  }

  async function handleToggleActive(entity: EntityApi) {
    try {
      remplacer(await entitiesApi.update(entity.id, { active: !entity.active }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Modification impossible");
    }
  }

  async function handleDelete(id: string) {
    try {
      await entitiesApi.remove(id);
      setEntities((prev) => prev.filter((e) => e.id !== id));
      invaliderBadges();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suppression impossible");
    }
  }






  const aveugles = entities.filter((e) => e.active && !e.can_alert);
  const operantes = entities.filter((e) => e.active && e.can_alert).length;
  const inactives = entities.filter((e) => !e.active).length;
  // Les filiales suivent leur groupe, en retrait : le périmètre se lit par
  // groupe. Une filiale dont le groupe n'est pas chargé reste à la racine.
  const ids = new Set(entities.map((e) => e.id));
  const ordonnees = entities
    .filter((e) => !e.parent_id || !ids.has(e.parent_id))
    .flatMap((racine) => [racine, ...entities.filter((e) => e.parent_id === racine.id)]);
  const affichees = filtreAveugles ? aveugles : ordonnees;
  const nbFiliales = entities.filter((e) => e.parent_id && ids.has(e.parent_id)).length;
  const groupesPossibles = entities
    .filter((e) => !e.parent_id)
    .sort((a, b) => a.name.localeCompare(b.name, "fr"));

  return (
    <div className="flex flex-col gap-3.5">
      {!admin && <LectureSeule quoi="la déclaration et la modification des organisations" />}

      {entities.length > 0 && (
        <div className="flex flex-col gap-3.5 lg:flex-row">
          {aveugles.length > 0 && (
            <div className="flex flex-1 flex-wrap items-center gap-4 rounded-[18px] border border-warn/30 bg-panel px-4 py-3.5">
              <span className="font-mono-data text-30 tabular-nums text-warn">{aveugles.length}</span>
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-ink">organisation(s) n&apos;alerteront jamais</p>
                <p className="text-body-sm text-ink-dim">
                  Sans sélecteur, ces organisations ne peuvent pas alerter.
                </p>
              </div>
              <button
                onClick={() => setFiltreAveugles((f) => !f)}
                aria-pressed={filtreAveugles}
                className="rounded-[10px] bg-warn px-3.5 py-2 text-12 font-semibold text-on-signal transition-opacity hover:opacity-90"
              >
                {filtreAveugles ? "Tout afficher" : `Corriger les ${aveugles.length}`}
              </button>
            </div>
          )}
          <div className="flex items-center gap-3.5 rounded-[18px] border border-line bg-panel px-4 py-3.5 lg:w-72">
            <span className="font-mono-data text-30 tabular-nums text-ink">{entities.length}</span>
            <p className="text-body-sm leading-tight text-ink-dim">
              organisation(s) déclarée(s)
              <br />
              {operantes} opérante(s) · {inactives} inactive(s)
              {nbFiliales > 0 && ` · ${nbFiliales} filiale(s)`}
            </p>
          </div>
        </div>
      )}

      {loadError && (
        <p className="rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger les organisations : {loadError}
        </p>
      )}
      {error && <p className="text-body-sm text-critical">{error}</p>}

      <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_21.5rem]">
        <div className="flex flex-col gap-2.5">
          <div className="flex flex-wrap items-center gap-3">
            <p className="font-mono-label text-11 text-ink-faint">
              {filtreAveugles
                ? admin
                  ? `${aveugles.length} organisation(s) sans sélecteur — ajoutez-en un sur chaque carte`
                  : `${aveugles.length} organisation(s) sans sélecteur — un administrateur doit en déclarer un`
                : "une détection dont le domaine ou l'email correspond à un sélecteur produit une alerte"}
            </p>
            {admin && !formOuvert && (
              <button
                onClick={() => setFormOuvert(true)}
                className="ml-auto rounded-[10px] bg-signal px-3.5 py-2 text-13 font-semibold text-on-signal transition-opacity hover:opacity-90"
              >
                Déclarer une organisation
              </button>
            )}
          </div>

          {admin && formOuvert && (
            <form onSubmit={(e) => void handleSubmit(e)} className="flex flex-col gap-2.5 rounded-[14px] border border-signal/25 bg-panel p-4">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nom de l'organisation" disabled={submitting} className={`${CHAMP} w-full`} />
              <div className="flex flex-wrap gap-2">
                <select value={nouveauParent} onChange={(e) => setNouveauParent(e.target.value)} disabled={submitting} className={`${CHAMP} min-w-[12rem] flex-1`} aria-label="Groupe">
                  <option value="">Organisation autonome (pas de groupe)</option>
                  {groupesPossibles.map((g) => (
                    <option key={g.id} value={g.id}>
                      filiale de {g.name}
                    </option>
                  ))}
                </select>
                <input
                  value={nouveauPays}
                  onChange={(e) => setNouveauPays(e.target.value.toUpperCase().slice(0, 2))}
                  placeholder="Pays (SN)"
                  aria-label="Pays (code ISO à deux lettres)"
                  disabled={submitting}
                  className={`${CHAMP} w-24 font-mono-data uppercase`}
                />
                <select value={nouveauSecteur} onChange={(e) => setNouveauSecteur(e.target.value)} disabled={submitting} className={CHAMP} aria-label="Secteur">
                  <option value="">Secteur non déclaré</option>
                  {secteurs.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                      {s.critical ? " (NIS2)" : ""}
                    </option>
                  ))}
                </select>
              </div>
              {selectors.map((selector, index) => (
                <div key={index} className="flex gap-2">
                  <select value={selector.type} onChange={(e) => updateSelector(index, { type: e.target.value as SelectorType })} disabled={submitting} className={CHAMP}>
                    {(Object.keys(SELECTOR_LABELS) as SelectorType[]).map((type) => (
                      <option key={type} value={type}>
                        {SELECTOR_LABELS[type]}
                      </option>
                    ))}
                  </select>
                  <input
                    value={selector.value}
                    onChange={(e) => updateSelector(index, { value: e.target.value })}
                    placeholder={selector.type === "keyword" ? "ex : MonEntreprise SA" : "ex : exemple.sn"}
                    disabled={submitting}
                    className={`${CHAMP} flex-1 font-mono-data`}
                  />
                  <button
                    type="button"
                    onClick={() => setSelectors((prev) => prev.filter((_, i) => i !== index))}
                    disabled={submitting || selectors.length === 1}
                    className="rounded-md p-2 text-ink-dim hover:bg-critical/15 hover:text-critical disabled:opacity-30"
                    title="Retirer ce sélecteur"
                  >
                    <Icon name="close" className="text-16" />
                  </button>
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" onClick={() => setSelectors((prev) => [...prev, emptySelector()])} disabled={submitting} className="font-mono-label text-11 text-signal disabled:opacity-50">
                  + sélecteur
                </button>
                <span className="flex-1" />
                <button type="button" onClick={() => setFormOuvert(false)} className="rounded-[10px] border border-line px-3.5 py-1.5 text-body-sm text-ink-dim hover:text-ink">
                  Annuler
                </button>
                <button type="submit" disabled={submitting || !name.trim() || (nouveauPays.length > 0 && nouveauPays.length !== 2)} className="rounded-[10px] bg-signal px-3.5 py-1.5 text-body-sm font-semibold text-on-signal disabled:opacity-50">
                  {submitting ? "Ajout…" : "Ajouter l'organisation"}
                </button>
              </div>
              {selectors.every((s) => !s.value.trim()) && (
                <p className="font-mono-label text-10.5 text-warn">
                  sans sélecteur, cette organisation ne produira jamais d&apos;alerte
                </p>
              )}
            </form>
          )}

          {loaded && entities.length === 0 && !loadError && (
            <div className="flex flex-col items-center gap-2 rounded-[18px] border border-signal/[0.14] bg-panel px-8 py-12 text-center">
              <p className="font-display text-19 font-bold text-ink">Aucune organisation surveillée</p>
              <p className="max-w-lg text-body-sm text-ink-dim">
                Tant qu&apos;aucune organisation n&apos;est déclarée avec au moins un sélecteur, la
                plateforme collecte et détecte, mais ne produira aucune alerte.
              </p>
            </div>
          )}

          {affichees.map((entity) => {
            const aveugle = entity.active && !entity.can_alert;
            const filiale = !filtreAveugles && !!entity.parent_id && ids.has(entity.parent_id);
            return (
              <div key={entity.id} className={`rounded-[14px] border bg-panel px-4 py-3.5 ${aveugle ? "border-warn/30" : "border-line"} ${filiale ? "ml-6 border-l-2 border-l-signal/30" : ""}`}>
                <div className="flex flex-wrap items-center gap-2.5">
                  <p className="text-15 font-semibold text-ink">{entity.name}</p>
                  {aveugle && (
                    <span className="rounded-md bg-warn/[0.14] px-2 py-0.5 font-mono-label text-10 text-warn">
                      ne peut pas alerter
                    </span>
                  )}
                  {!entity.active && (
                    <span className="rounded-md bg-panel-raised px-2 py-0.5 font-mono-label text-10 text-ink-dim">inactive</span>
                  )}
                  {entity.verification_status === "verified" && (
                    <span className="rounded-md bg-signal/10 px-2 py-0.5 font-mono-label text-10 text-signal">vérifiée</span>
                  )}
                  <span className="ml-auto font-mono-data text-11 text-ink-dim">
                    {entity.selectors.length} sélecteur(s)
                  </span>
                  <div className="flex gap-0.5">
                    <button onClick={() => void handleToggleDocuments(entity.id)} disabled={loadingDocumentsId === entity.id} className={`rounded-md p-1.5 transition-colors disabled:opacity-50 ${expandedEntityId === entity.id ? "bg-signal/10 text-signal" : "text-ink-dim hover:bg-signal/15 hover:text-signal"}`} title="Documents qui mentionnent cette organisation">
                      <Icon name={loadingDocumentsId === entity.id ? "progress_activity" : "description"} className={`text-16 ${loadingDocumentsId === entity.id ? "animate-spin" : ""}`} />
                    </button>
                    {admin && entity.selectors.some((s) => s.type === "domain") && (
                      <>
                        <button onClick={() => void handleDiscoverSubdomains(entity.id)} disabled={discoveringId === entity.id} className="rounded-md p-1.5 text-ink-dim hover:bg-signal/15 hover:text-signal disabled:opacity-50" title="Découvrir des sous-domaines — service public de certificats, en clair, hors Tor">
                          <Icon name={discoveringId === entity.id ? "progress_activity" : "travel_explore"} className={`text-16 ${discoveringId === entity.id ? "animate-spin" : ""}`} />
                        </button>
                        <button onClick={() => void handleCorroborateIntelx(entity.id)} disabled={corroboratingId === entity.id} className="rounded-md p-1.5 text-ink-dim hover:bg-signal/15 hover:text-signal disabled:opacity-50" title="Corroborer via IntelX (quota limité, à utiliser avec parcimonie)">
                          <Icon name={corroboratingId === entity.id ? "progress_activity" : "search_insights"} className={`text-16 ${corroboratingId === entity.id ? "animate-spin" : ""}`} />
                        </button>
                      </>
                    )}
                    {admin && (
                      <>
                        <button onClick={() => void handleToggleActive(entity)} className="rounded-md p-1.5 text-ink-dim hover:bg-signal/15 hover:text-signal" title={entity.active ? "Désactiver" : "Activer"}>
                          <Icon name={entity.active ? "toggle_on" : "toggle_off"} className="text-18" />
                        </button>
                        <button onClick={() => void handleDelete(entity.id)} className="rounded-md p-1.5 text-ink-dim hover:bg-critical/15 hover:text-critical" title="Supprimer">
                          <Icon name="delete" className="text-16" />
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                  {entity.selectors.map((selector) => (
                    <span key={selector.id} className="rounded-md border border-line bg-panel-sunken px-2 py-1 font-mono-data text-11 text-ink" title={SELECTOR_LABELS[selector.type]}>
                      {selector.type === "keyword" ? `« ${selector.value} »` : selector.value}
                    </span>
                  ))}
                  {!admin ? null : ajoutPour === entity.id ? (
                    <span className="flex items-center gap-1.5">
                      <select value={ajoutType} onChange={(e) => setAjoutType(e.target.value as SelectorType)} disabled={ajoutEnCours} className={`${CHAMP} py-1 text-11`}>
                        {(Object.keys(SELECTOR_LABELS) as SelectorType[]).map((t) => (
                          <option key={t} value={t}>
                            {SELECTOR_LABELS[t]}
                          </option>
                        ))}
                      </select>
                      <input
                        autoFocus
                        value={ajoutValeur}
                        onChange={(e) => setAjoutValeur(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void handleAjoutSelecteur(entity);
                          if (e.key === "Escape") setAjoutPour(null);
                        }}
                        disabled={ajoutEnCours}
                        placeholder={ajoutType === "keyword" ? "raison sociale" : "exemple.sn"}
                        className={`${CHAMP} w-44 py-1 font-mono-data text-11`}
                      />
                      <button onClick={() => void handleAjoutSelecteur(entity)} disabled={ajoutEnCours || !ajoutValeur.trim()} className="rounded-md p-1 text-signal hover:bg-signal/15 disabled:opacity-40" title="Ajouter">
                        <Icon name="check" className="text-15" />
                      </button>
                      <button onClick={() => setAjoutPour(null)} className="rounded-md p-1 text-ink-dim hover:bg-panel-raised" title="Annuler">
                        <Icon name="close" className="text-15" />
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => {
                        setAjoutPour(entity.id);
                        setAjoutType("domain");
                        setAjoutValeur("");
                      }}
                      className={`rounded-md border border-dashed px-2 py-1 font-mono-data text-11 transition-colors ${aveugle ? "border-warn/50 text-warn" : "border-line text-ink-faint hover:text-ink"}`}
                    >
                      + sélecteur
                    </button>
                  )}
                </div>

                <FicheOrganisation entite={entity} toutes={entities} secteurs={secteurs} admin={admin} onModifiee={remplacer} />

                <p className={`mt-2 text-body-sm ${aveugle ? "text-warn" : "text-ink-dim"}`}>
                  {!entity.active
                    ? "Inactive : aucune alerte ne sera produite pour cette organisation."
                    : aveugle
                      ? "Aucun sélecteur : le moteur n'a rien à comparer, cette organisation ne produira jamais d'alerte."
                      : "Surveillance opérante : une détection qui correspond à l'un de ces sélecteurs produit une alerte."}
                </p>

                {discoveryError[entity.id] && <p className="mt-2 text-body-sm text-critical">Recherche de sous-domaines impossible : {discoveryError[entity.id]}</p>}
                {discoveryResults[entity.id] && (
                  <div className="mt-2.5 rounded-xl border border-line bg-panel-sunken p-3">
                    {discoveryResults[entity.id].discovered.length === 0 ? (
                      <p className="text-body-sm text-ink-dim">Aucun sous-domaine supplémentaire trouvé.</p>
                    ) : (
                      <>
                        <p className="mb-2 font-mono-label text-11 text-ink-dim">
                          {discoveryResults[entity.id].discovered.length} sous-domaine(s)
                        </p>
                        <div className="mb-2.5 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                          {discoveryResults[entity.id].discovered.map((subdomain) => {
                            const isSelected = selectedSubdomains[entity.id]?.has(subdomain) ?? false;
                            return (
                              <label key={subdomain} className={`flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 font-mono-data text-11 ${isSelected ? "border-signal/40 bg-signal/10 text-signal" : "border-line text-ink-dim"}`}>
                                <input type="checkbox" checked={isSelected} onChange={() => toggleSubdomainSelection(entity.id, subdomain)} className="accent-signal" />
                                {subdomain}
                              </label>
                            );
                          })}
                        </div>
                        <button onClick={() => void handleAddSelectedSubdomains(entity)} disabled={addingSubdomains === entity.id || !selectedSubdomains[entity.id]?.size} className="rounded-[10px] bg-signal px-3 py-1.5 text-12 font-semibold text-on-signal disabled:opacity-50">
                          Ajouter {selectedSubdomains[entity.id]?.size ?? 0} sélecteur(s)
                        </button>
                      </>
                    )}
                  </div>
                )}

                {corroborationError[entity.id] && <p className="mt-2 text-body-sm text-critical">Corroboration IntelX impossible : {corroborationError[entity.id]}</p>}
                {corroborationResults[entity.id] && (
                  <div className="mt-2.5 rounded-xl border border-line bg-panel-sunken p-3">
                    {corroborationResults[entity.id].results.map((r) => (
                      <div key={r.domain} className="mb-2 last:mb-0">
                        <p className="text-body-sm text-ink">
                          {/* Le compteur IntelX SATURE à 200 : lire « au moins », jamais une ampleur. */}
                          <span className="font-mono-data">{r.domain}</span> — {r.is_truncated ? `au moins ${r.hit_count}` : r.hit_count} correspondance(s) sur IntelX
                        </p>
                        {Object.keys(r.buckets).length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1.5">
                            {Object.entries(r.buckets).map(([bucket, count]) => (
                              <span key={bucket} className="rounded-md bg-panel-raised px-2 py-0.5 font-mono-data text-11 text-ink-dim">
                                {bucket} : {count}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {expandedEntityId === entity.id && (
                  <div className="mt-2.5 rounded-xl border border-line bg-panel-sunken p-3">
                    {documentsError[entity.id] && <p className="text-body-sm text-critical">Impossible de charger les documents : {documentsError[entity.id]}</p>}
                    {!documentsError[entity.id] && loadingDocumentsId === entity.id && <p className="text-body-sm text-ink-dim">Chargement des documents…</p>}
                    {!documentsError[entity.id] && loadingDocumentsId !== entity.id && entityDocuments[entity.id] && (
                      <>
                        <p className="mb-2 font-mono-label text-11 text-ink-dim">
                          {entityDocumentsTotal[entity.id] === 0
                            ? "Aucun document ne mentionne cette organisation pour l'instant."
                            : `${entityDocumentsTotal[entity.id]} document(s)` +
                              (entityDocumentsTotal[entity.id] > entityDocuments[entity.id].length ? ` · ${entityDocuments[entity.id].length} affiché(s)` : "")}
                        </p>
                        <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
                          {entityDocuments[entity.id].map((doc) => (
                            <button key={doc.id} onClick={() => setOpenDocumentId(doc.id)} className="rounded-lg border border-line px-2.5 py-2 text-left transition-colors hover:border-signal/30">
                              <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-body-sm text-ink">{doc.title || "(sans titre)"}</span>
                                <span className="shrink-0 font-mono-data text-11 text-ink-faint">{jour(doc.fetched_at)}</span>
                              </div>
                              <p className="mt-0.5 truncate text-12 text-ink-dim">
                                {doc.source_name ?? doc.source_type} — {doc.content_preview}
                              </p>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <aside className="rounded-[18px] border border-line bg-panel p-4">
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">Entités candidates</h2>
          <p className="mt-1 text-body-sm text-ink-dim">
            Repérées dans le corpus, pas encore surveillées.
          </p>

          {admin && (
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={() => void handleStartBackfill()} disabled={backfillJob?.status === "running"} className="rounded-[10px] border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink transition-colors hover:border-signal/35 disabled:opacity-50">
              {backfillJob?.status === "running" ? "Analyse…" : "Analyser le corpus"}
            </button>
            {candidates.length > 0 && (
              <button onClick={() => void handleFilterWithLlm()} disabled={llmFiltering} title="Demande au modèle d'écarter le bruit résiduel (vocabulaire de forum, acronymes…)" className="rounded-[10px] border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink transition-colors hover:border-signal/35 disabled:opacity-50">
                {llmFiltering ? "Filtrage…" : "Filtrer avec l'IA"}
              </button>
            )}
          </div>
          )}
          {backfillJob?.status === "running" && (
            <p className="mt-2 font-mono-label text-10.5 text-ink-dim">
              {backfillJob.done} / {backfillJob.total} documents · {backfillJob.created_count} détection(s)
            </p>
          )}
          {backfillJob?.status === "done" && (
            <p className="mt-2 font-mono-label text-10.5 text-ink-dim">analyse terminée · {backfillJob.created_count} détection(s)</p>
          )}
          {llmKeptNames && (
            <p className="mt-2 font-mono-label text-10.5 text-ink-dim">
              {displayedCandidates.length} / {candidates.length} retenue(s) par le modèle ·{" "}
              <button onClick={() => setLlmKeptNames(null)} className="text-signal">
                tout afficher
              </button>
            </p>
          )}
          {(backfillError || llmFilterError || candidatesError) && (
            <p className="mt-2 text-body-sm text-critical">{backfillError ?? llmFilterError ?? candidatesError}</p>
          )}

          <div className="custom-scrollbar mt-3 flex max-h-[28rem] flex-col gap-1.5 overflow-y-auto pr-1">
            {displayedCandidates.length === 0 && !candidatesError ? (
              <p className="text-body-sm text-ink-dim">
                {llmKeptNames ? "Aucune candidate retenue par le modèle." : "Aucune candidate pour l'instant."}
              </p>
            ) : (
              displayedCandidates.map((candidate) => (
                <div key={candidate.name} className="flex items-center gap-2 rounded-[10px] border border-line bg-panel-sunken px-2.5 py-2">
                  <button
                    onClick={() => setCitationsDe(candidate.name)}
                    className="min-w-0 flex-1 text-left"
                    title="Voir où elle est citée"
                  >
                    <p className="truncate font-mono-data text-12 text-ink">{candidate.name}</p>
                    <p className="font-mono-label text-10 text-ink-faint underline decoration-dotted underline-offset-2">
                      {candidate.count} mention{candidate.count > 1 ? "s" : ""} · voir où
                    </p>
                  </button>
                  {admin && (
                    <button onClick={() => handleUseCandidate(candidate)} className="rounded-md bg-panel-raised px-2 py-1 font-mono-label text-10 text-signal hover:bg-signal/15">
                      créer
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
          <p className="mt-3 font-mono-label text-10 text-ink-faint">
            créée depuis une candidate, l&apos;organisation reçoit sa raison sociale comme sélecteur
          </p>
        </aside>
      </div>

      {citationsDe && !openDocumentId && (
        <CitationsCandidate
          nom={citationsDe}
          onFermer={() => setCitationsDe(null)}
          onOuvrirDocument={setOpenDocumentId}
        />
      )}
      {openDocumentId && <DocumentDetailPanel documentId={openDocumentId} onClose={() => setOpenDocumentId(null)} />}
    </div>
  );
}
