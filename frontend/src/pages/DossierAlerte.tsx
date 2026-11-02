import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { alertsApi, type AlertApi, type AlertEvidenceResponse } from "../api/alerts";
import { entitiesApi, type EntityApi } from "../api/entities";
import { ModeOperatoire } from "../components/alertes/ModeOperatoire";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { domaineAlerte, referenceCourte, sujetAlerte } from "../lib/alertes";
import { invaliderBadges } from "../hooks/useVeilleBadges";
import { useRequete } from "../hooks/useRequete";
import { EnteteDossier } from "../components/alertes/dossier/EnteteDossier";
import { FaitsEtablis } from "../components/alertes/dossier/FaitsEtablis";
import { PreuveDossier } from "../components/alertes/dossier/PreuveDossier";
import { ChaineDocumentaire } from "../components/alertes/dossier/ChaineDocumentaire";
import { ResumeIA } from "../components/alertes/dossier/ResumeIA";
import { RenseignementsVictime } from "../components/alertes/dossier/RenseignementsVictime";
import { Corroboration } from "../components/alertes/dossier/Corroboration";
import { JournalNote } from "../components/alertes/dossier/JournalNote";
import { CorrectionAnalyste } from "../components/alertes/dossier/CorrectionAnalyste";
import type { ContexteDossier } from "../components/alertes/dossier/contexte";






/** Le dossier d'une alerte : ce qu'un analyste doit pouvoir contester.
 *
 * ⚠️ L'alerte était une LIGNE DE TABLEAU À SEPT COLONNES. Les faits établis,
 * la preuve consultable, le raisonnement de gravité, les documents d'origine
 * et le travail de l'analyste n'y tenaient pas. Or le produit revendique la
 * vérifiabilité : une alerte qu'on ne peut pas remonter jusqu'au texte
 * collecté n'est qu'une affirmation.
 */
/** Qui a vu la victime en premier : notre collecte ou la PREMIÈRE indexation
 * par un agrégateur. ⚠️ `corroboration_first_seen_at` est le minimum sur TOUS
 * les observateurs (RansomLook, ransomware.live) : l'attribuer à RansomLook
 * était faux (compagnie-aerienne : 12:09 vient de ransomware.live, RansomLook dit
 * 13:45). Rien si l'une des deux dates manque — on n'invente pas d'écart.
 * ⚠️ Un retard est normal pour une victime ancienne découverte lors d'une
 * première collecte du site : il se lit tel quel, sans l'embellir. */
function avanceSurTiers(collecteeLe: string | null, indexeeLe: string | null): string | null {
  if (!collecteeLe || !indexeeLe) return null;
  const ecart = new Date(indexeeLe).getTime() - new Date(collecteeLe).getTime();
  const heures = Math.round(Math.abs(ecart) / 3_600_000);
  if (heures === 0) return "vue en même temps que les agrégateurs";
  const duree = heures < 48 ? `${heures} h` : `${Math.round(heures / 24)} j`;
  return ecart > 0
    ? `vue par nous ${duree} avant les agrégateurs`
    : `un agrégateur l'avait indexée ${duree} avant notre collecte`;
}

/** Nom lisible d'un observateur tiers de corroboration. */
function nomObservateur(code: string): string {
  return { ransomlook: "RansomLook", ransomware_live: "ransomware.live" }[code] ?? code;
}

export function DossierAlerte() {
  const { id = "" } = useParams();
  // ⚠️ Passer d'un dossier à un autre SANS démonter le composant (un lien de
  // la chaîne documentaire, le retour arrière) laisserait l'ancienne alerte à
  // l'écran pendant le chargement de la nouvelle : `garderPendantChargement`
  // à faux, et seule la réponse du dossier AFFICHÉ est retenue.
  const dossier = useRequete(
    async () => {
      const [a, entites] = await Promise.all([alertsApi.get(id), entitiesApi.list()]);
      return { alerte: a, entitesParId: Object.fromEntries(entites.map((e) => [e.id, e])) };
    },
    [id],
    { garderPendantChargement: false },
  );
  // La chaîne documentaire ne bloque pas le dossier : un échec ici laisse les
  // faits et la preuve lisibles.
  const preuvesReq = useRequete(() => alertsApi.documents(id), [id], { garderPendantChargement: false });
  const alerte: AlertApi | null = dossier.donnees?.alerte ?? null;
  const entitesParId: Record<string, EntityApi> = dossier.donnees?.entitesParId ?? {};
  const preuves: AlertEvidenceResponse | null = preuvesReq.donnees;
  const chargement = dossier.chargement;
  // Erreur d'une ACTION (statut, PDF, STIX), distincte du chargement.
  const [erreurAction, setErreur] = useState<string | null>(null);
  const erreur = dossier.erreur ?? erreurAction;
  const modifierDossier = dossier.modifier;
  const setAlerte = (a: AlertApi) => modifierDossier((d) => (d ? { ...d, alerte: a } : d));
  const [enCours, setEnCours] = useState<string | null>(null);

  // Téléchargements : même verrou que les actions, pour qu'un clic pendant la
  // rédaction (17 à 74 s mesurées pour le PDF) ne relance pas une génération.
  async function telecharger(nom: string, action: () => Promise<void>) {
    setEnCours(nom);
    setErreur(null);
    try {
      await action();
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setEnCours(null);
    }
  }

  async function agir(nom: string, action: () => Promise<AlertApi>) {
    setEnCours(nom);
    setErreur(null);
    try {
      setAlerte(await action());
      // Le compteur d'alertes ouvertes de la barre latérale devient faux dès
      // qu'on acquitte ou résout : on invalide plutôt que de le laisser mentir.
      invaliderBadges();
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setEnCours(null);
    }
  }

  if (chargement) {
    return (
      <AppLayout title="Dossier d'alerte">
        <p className="text-body-sm text-ink-dim">Chargement du dossier…</p>
      </AppLayout>
    );
  }

  if (!alerte) {
    return (
      <AppLayout title="Dossier d'alerte">
        <div className="pulse-panel flex flex-col items-center gap-2.5 px-8 py-14 text-center">
          <h2 className="font-display text-headline-md text-ink">Alerte introuvable</h2>
          <p className="max-w-md text-body-sm text-ink-dim">
            {erreur ?? "Cette alerte n'existe plus, ou l'identifiant est incorrect."}
          </p>
          <Link
            to="/alerts"
            className="mt-2 rounded-md border border-line bg-panel-raised px-3.5 py-2 text-body-sm text-ink"
          >
            Retour aux alertes
          </Link>
        </div>
      </AppLayout>
    );
  }

  const sujet = sujetAlerte(alerte, entitesParId);
  const domaine = domaineAlerte(alerte, entitesParId);
  const confirmee = alerte.corroboration_status === "corroborated";
  const exclusive = alerte.corroboration_status === "exclusive";
  const sansObjet = alerte.corroboration_status === "not_applicable";
  // Tous les groupes qui revendiquent la victime, pas seulement le premier :
  // une double revendication est une information, pas un bruit.
  const autresGroupes = (alerte.corroborated_groups ?? []).filter(
    (g) => g !== alerte.corroborated_group,
  );
  // Observateurs tiers ayant confirmé (RansomLook, ransomware.live) — leur
  // union augmente la couverture. Noms lisibles.
  const observateurs = (alerte.corroboration_observers ?? []).map(nomObservateur);
  // ⚠️ « mesuré et nul » n'est PAS « jamais mesuré » : sans
  // `intel_refreshed_at`, afficher « 0 exposition » ferait passer une absence
  // de mesure pour un résultat rassurant. Même convention que
  // `corroboration_status` null.
  // ⚠️ Mesurée = la SOURCE a fourni un compteur, pas « la passe a tourné ».
  // ransomware.live a retiré ce champ vers le 2026-09-23 : une passe réussie
  // sans compteur ne doit pas afficher « 0 identifiant exposé ».
  const expositionMesuree =
    alerte.compromised_employees != null || alerte.compromised_users != null;
  const documents = preuves?.documents ?? [];
  // Le document d'origine est presque toujours un `.onion` : affiché, jamais
  // cliquable — il exige Tor.
  const documentPrincipal = documents[0] ?? null;
  const avance = avanceSurTiers(
    documentPrincipal?.fetched_at ?? null,
    alerte.corroboration_first_seen_at,
  );

  const contexte: ContexteDossier = {
    alerte,
    sujet,
    domaine,
    enCours,
    telecharger,
    agir,
    confirmee,
    exclusive,
    sansObjet,
    autresGroupes,
    observateurs,
    expositionMesuree,
    documents,
    documentPrincipal,
    avance,
    preuves,
    entitesParId,
  };

  return (
    <AppLayout title="Dossier d'alerte">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Link
          to="/alerts"
          className="flex items-center gap-1.5 font-mono-label text-11 text-ink-dim transition-colors hover:text-ink"
        >
          <Icon name="chevron_right" className="rotate-180 text-13" />
          alertes
        </Link>
        <span className="font-mono-label text-11 text-ink-faint">
          /alerts/{referenceCourte(alerte)}
        </span>
      </div>

      {erreur && (
        <p className="mb-4 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          {erreur}
        </p>
      )}

      <EnteteDossier c={contexte} />

      <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex flex-col gap-3.5">
          <FaitsEtablis c={contexte} />

          <PreuveDossier c={contexte} />

          <ChaineDocumentaire c={contexte} />
        </div>

        {/* ---- rail ---- */}
        <aside className="flex flex-col gap-3.5">
          <ResumeIA c={contexte} />

          <CorrectionAnalyste key={`${contexte.alerte.id}-${contexte.alerte.override_at ?? ""}`} c={contexte} />

          <RenseignementsVictime c={contexte} />

          <ModeOperatoire alertId={alerte.id} />

          <Corroboration c={contexte} />

          <JournalNote key={contexte.alerte.id} c={contexte} />
        </aside>
      </div>
    </AppLayout>
  );
}
