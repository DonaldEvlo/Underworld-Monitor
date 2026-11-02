import { useEffect, useRef, useState } from "react";
import type { DocumentListItem } from "../../api/documents";
import {
  entitiesApi,
  type EntityApi,
  type IntelXCorroborationResult,
  type OrganizationBackfillJobStatus,
  type OrganizationCandidate,
  type SelectorInput,
  type SubdomainDiscoveryResult,
} from "../../api/entities";

/** Logique de la page Organisations, sortie du composant d'affichage.
 *
 * ⚠️ `EntitiesPanel` portait 32 `useState` et une dizaine de gestionnaires
 * dans un seul composant de 700 lignes : on ne pouvait plus lire ce qu'une
 * action modifiait. Chaque hook ci-dessous regroupe UN domaine — candidats
 * détectés, sous-domaines, corroboration IntelX, documents rattachés — avec
 * son état et ses gestes.
 */

const BACKFILL_POLL_INTERVAL_MS = 3000;

/** Organisations candidates détectées dans le corpus, leur filtrage par le
 * modèle, et la passe de rattrapage (tâche de fond suivie par sondage). */
export function useCandidats() {
  const [candidates, setCandidates] = useState<OrganizationCandidate[]>([]);
  const [candidatesError, setCandidatesError] = useState<string | null>(null);
  const [backfillJob, setBackfillJob] = useState<OrganizationBackfillJobStatus | null>(null);
  const [backfillError, setBackfillError] = useState<string | null>(null);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [llmFiltering, setLlmFiltering] = useState(false);
  const [llmFilterError, setLlmFilterError] = useState<string | null>(null);
  const [llmKeptNames, setLlmKeptNames] = useState<Set<string> | null>(null);

  function loadCandidates() {
    entitiesApi
      .listCandidates()
      .then((result) => {
        setCandidates(result);
        setLlmKeptNames(null);
      })
      .catch((err) => setCandidatesError(err instanceof Error ? err.message : "Erreur inconnue"));
  }

  async function handleFilterWithLlm() {
    setLlmFiltering(true);
    setLlmFilterError(null);
    try {
      const { kept } = await entitiesApi.filterCandidatesWithLlm(candidates.map((c) => c.name));
      setLlmKeptNames(new Set(kept));
    } catch (err) {
      setLlmFilterError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLlmFiltering(false);
    }
  }

  const displayedCandidates = llmKeptNames ? candidates.filter((c) => llmKeptNames.has(c.name)) : candidates;

  // Les candidats suivent une tâche de fond (sondage) : ce n'est pas un
  // chargement de page, il garde son propre effet.
  useEffect(() => {
    loadCandidates();
    return () => {
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    };
  }, []);

  function pollBackfillStatus(jobId: string) {
    entitiesApi
      .getBackfillStatus(jobId)
      .then((status) => {
        setBackfillJob(status);
        if (status.status === "running") {
          pollTimeoutRef.current = setTimeout(() => pollBackfillStatus(jobId), BACKFILL_POLL_INTERVAL_MS);
        } else {
          if (status.status === "done") loadCandidates();
          if (status.status === "error") setBackfillError(status.error ?? "Erreur inconnue");
        }
      })
      .catch((err) => setBackfillError(err instanceof Error ? err.message : "Erreur inconnue"));
  }

  async function handleStartBackfill() {
    setBackfillError(null);
    try {
      const status = await entitiesApi.startOrganizationBackfill();
      setBackfillJob(status);
      pollTimeoutRef.current = setTimeout(() => pollBackfillStatus(status.job_id), BACKFILL_POLL_INTERVAL_MS);
    } catch (err) {
      setBackfillError(err instanceof Error ? err.message : "Erreur inconnue");
    }
  }

  return {
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
  };
}

/** Découverte de sous-domaines (certificats publics) et ajout comme sélecteurs. */
export function useSousDomaines(remplacer: (entite: EntityApi) => void) {
  const [discoveringId, setDiscoveringId] = useState<string | null>(null);
  const [discoveryError, setDiscoveryError] = useState<Record<string, string>>({});
  const [discoveryResults, setDiscoveryResults] = useState<Record<string, SubdomainDiscoveryResult>>({});
  const [selectedSubdomains, setSelectedSubdomains] = useState<Record<string, Set<string>>>({});
  const [addingSubdomains, setAddingSubdomains] = useState<string | null>(null);

  async function handleDiscoverSubdomains(entityId: string) {
    setDiscoveringId(entityId);
    setDiscoveryError((prev) => ({ ...prev, [entityId]: "" }));
    try {
      const result = await entitiesApi.discoverSubdomains(entityId);
      setDiscoveryResults((prev) => ({ ...prev, [entityId]: result }));
      setSelectedSubdomains((prev) => ({ ...prev, [entityId]: new Set(result.discovered) }));
    } catch (err) {
      setDiscoveryError((prev) => ({ ...prev, [entityId]: err instanceof Error ? err.message : "Erreur inconnue" }));
    } finally {
      setDiscoveringId(null);
    }
  }

  function toggleSubdomainSelection(entityId: string, subdomain: string) {
    setSelectedSubdomains((prev) => {
      const current = new Set(prev[entityId] ?? []);
      if (current.has(subdomain)) current.delete(subdomain);
      else current.add(subdomain);
      return { ...prev, [entityId]: current };
    });
  }

  async function handleAddSelectedSubdomains(entity: EntityApi) {
    const selected = selectedSubdomains[entity.id];
    if (!selected || selected.size === 0) return;
    setAddingSubdomains(entity.id);
    try {
      const existing: SelectorInput[] = entity.selectors.map((s) => ({ type: s.type, value: s.value }));
      const additions: SelectorInput[] = Array.from(selected).map((value) => ({ type: "domain", value }));
      remplacer(await entitiesApi.update(entity.id, { selectors: [...existing, ...additions] }));
      setDiscoveryResults((prev) => {
        const suite = { ...prev };
        delete suite[entity.id];
        return suite;
      });
    } catch (err) {
      setDiscoveryError((prev) => ({ ...prev, [entity.id]: err instanceof Error ? err.message : "Ajout impossible" }));
    } finally {
      setAddingSubdomains(null);
    }
  }

  return {
    discoveringId,
    discoveryError,
    discoveryResults,
    selectedSubdomains,
    addingSubdomains,
    handleDiscoverSubdomains,
    toggleSubdomainSelection,
    handleAddSelectedSubdomains,
  };
}

/** Corroboration IntelX d'un domaine de sélecteur (exposition, binaire). */
export function useCorroborationIntelx() {
  const [corroboratingId, setCorroboratingId] = useState<string | null>(null);
  const [corroborationError, setCorroborationError] = useState<Record<string, string>>({});
  const [corroborationResults, setCorroborationResults] = useState<Record<string, IntelXCorroborationResult>>({});

  async function handleCorroborateIntelx(entityId: string) {
    setCorroboratingId(entityId);
    setCorroborationError((prev) => ({ ...prev, [entityId]: "" }));
    try {
      const result = await entitiesApi.corroborateIntelx(entityId);
      setCorroborationResults((prev) => ({ ...prev, [entityId]: result }));
    } catch (err) {
      setCorroborationError((prev) => ({ ...prev, [entityId]: err instanceof Error ? err.message : "Erreur inconnue" }));
    } finally {
      setCorroboratingId(null);
    }
  }

  return { corroboratingId, corroborationError, corroborationResults, handleCorroborateIntelx };
}

/** Documents rattachés à une organisation, chargés au dépliage puis gardés. */
export function useDocumentsEntite() {
  const [expandedEntityId, setExpandedEntityId] = useState<string | null>(null);
  const [entityDocuments, setEntityDocuments] = useState<Record<string, DocumentListItem[]>>({});
  const [entityDocumentsTotal, setEntityDocumentsTotal] = useState<Record<string, number>>({});
  const [loadingDocumentsId, setLoadingDocumentsId] = useState<string | null>(null);
  const [documentsError, setDocumentsError] = useState<Record<string, string>>({});

  async function handleToggleDocuments(entityId: string) {
    if (expandedEntityId === entityId) {
      setExpandedEntityId(null);
      return;
    }
    setExpandedEntityId(entityId);
    if (entityDocuments[entityId]) return; // déjà chargé
    setLoadingDocumentsId(entityId);
    setDocumentsError((prev) => ({ ...prev, [entityId]: "" }));
    try {
      const result = await entitiesApi.listDocuments(entityId);
      setEntityDocuments((prev) => ({ ...prev, [entityId]: result.items }));
      setEntityDocumentsTotal((prev) => ({ ...prev, [entityId]: result.total }));
    } catch (err) {
      setDocumentsError((prev) => ({ ...prev, [entityId]: err instanceof Error ? err.message : "Erreur inconnue" }));
    } finally {
      setLoadingDocumentsId(null);
    }
  }

  return {
    expandedEntityId,
    entityDocuments,
    entityDocumentsTotal,
    loadingDocumentsId,
    documentsError,
    handleToggleDocuments,
  };
}
