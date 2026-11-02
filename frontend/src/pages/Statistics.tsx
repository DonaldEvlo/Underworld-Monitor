import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { alertsApi, type AlertApi } from "../api/alerts";
import { statsApi, type EntitySummaryApi } from "../api/stats";
import { useAuth } from "../context/auth-context";
import { peutAcceder } from "../lib/roles";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { MaskedValue } from "../components/ui/MaskedValue";
import { SeverityBadge } from "../components/ui/SeverityBadge";
import { detectionTypeLabels, severityFond, severityLabels } from "../lib/taxonomy";
import type { AlertSeverity } from "../types/domain";
import { dateHeure } from "../lib/format";
import { useRequete } from "../hooks/useRequete";

const SEVERITY_ORDER: AlertSeverity[] = ["critical", "high", "medium", "low"];

// Couleur de segment par gravité — mêmes teintes que les pastilles.

const JOURS_HISTOGRAMME = 30;
const TAILLE_PAGE = 200;
// Borne de sécurité : au-delà, les indicateurs sont calculés sur un
// échantillon — et l'écran le DIT, plutôt que d'afficher un chiffre partiel
// comme s'il était complet.
const PLAFOND_ALERTES = 2000;

interface ChargeAlertes {
  alertes: AlertApi[];
  total: number;
}

async function chargerToutesLesAlertes(): Promise<ChargeAlertes> {
  const alertes: AlertApi[] = [];
  let total: number;
  let offset = 0;
  for (;;) {
    const page = await alertsApi.list({ offset, limit: TAILLE_PAGE });
    total = page.total;
    alertes.push(...page.items);
    offset += page.items.length;
    if (page.items.length === 0 || offset >= total || alertes.length >= PLAFOND_ALERTES) break;
  }
  return { alertes, total };
}


function detectionTypeLabel(type: string): string {
  return detectionTypeLabels[type as keyof typeof detectionTypeLabels] ?? type;
}

function jourIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const j = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${j}`;
}

function formatDuree(ms: number): string {
  const heures = ms / 3_600_000;
  if (heures < 1) return `${Math.max(1, Math.round(ms / 60_000))} min`;
  if (heures < 48) return `${Math.round(heures)} h`;
  return `${Math.round(heures / 24)} j`;
}

function mediane(valeurs: number[]): number | null {
  if (valeurs.length === 0) return null;
  const tri = [...valeurs].sort((a, b) => a - b);
  const milieu = Math.floor(tri.length / 2);
  return tri.length % 2 ? tri[milieu] : (tri[milieu - 1] + tri[milieu]) / 2;
}

interface Indicateurs {
  ouvertes: number;
  resolues: number;
  fauxPositifs: number;
  delaiMedianMs: number | null;
  delaisMesures: number;
  parGravite: Record<AlertSeverity, number>;
  jours: { date: string; parGravite: Record<AlertSeverity, number>; total: number }[];
  maxJour: number;
  horsFenetre: number;
}

function calculerIndicateurs(alertes: AlertApi[]): Indicateurs {
  const vide = (): Record<AlertSeverity, number> => ({ critical: 0, high: 0, medium: 0, low: 0 });
  const parGravite = vide();
  const delais: number[] = [];
  let ouvertes = 0;
  let resolues = 0;
  let fauxPositifs = 0;

  const aujourdHui = new Date();
  const jours = Array.from({ length: JOURS_HISTOGRAMME }, (_, i) => {
    const d = new Date(aujourdHui);
    d.setDate(d.getDate() - (JOURS_HISTOGRAMME - 1 - i));
    return { date: jourIso(d), parGravite: vide(), total: 0 };
  });
  const indexJour = new Map(jours.map((j, i) => [j.date, i]));
  let horsFenetre = 0;

  for (const a of alertes) {
    parGravite[a.severity] = (parGravite[a.severity] ?? 0) + 1;
    if (a.status === "open") ouvertes += 1;
    if (a.status === "resolved") {
      resolues += 1;
      if (a.resolution_reason === "false_positive") fauxPositifs += 1;
      // Délai mesuré de la création à la résolution — seulement quand la date
      // de résolution a été enregistrée (les alertes antérieures au suivi
      // d'analyste n'en ont pas : les compter pour zéro fausserait la médiane).
      if (a.resolved_at) {
        const delta = new Date(a.resolved_at).getTime() - new Date(a.created_at).getTime();
        if (delta >= 0) delais.push(delta);
      }
    }
    const i = indexJour.get(a.alert_date.slice(0, 10));
    if (i === undefined) {
      horsFenetre += 1;
    } else {
      jours[i].parGravite[a.severity] += 1;
      jours[i].total += 1;
    }
  }

  return {
    ouvertes,
    resolues,
    fauxPositifs,
    delaiMedianMs: mediane(delais),
    delaisMesures: delais.length,
    parGravite,
    jours,
    maxJour: Math.max(1, ...jours.map((j) => j.total)),
    horsFenetre,
  };
}

function CarteIndicateur({
  libelle,
  valeur,
  detail,
  ton = "text-ink",
}: {
  libelle: string;
  valeur: string;
  detail: string;
  ton?: string;
}) {
  return (
    <div className="pulse-panel p-4">
      <p className="text-11 font-medium uppercase tracking-[0.08em] text-ink-faint">{libelle}</p>
      <p className={`mt-1 font-mono-data text-26 leading-tight tabular-nums ${ton}`}>{valeur}</p>
      <p className="mt-1 text-body-sm text-ink-dim">{detail}</p>
    </div>
  );
}

function HistogrammeJournalier({ ind }: { ind: Indicateurs }) {
  const [survol, setSurvol] = useState<number | null>(null);
  const jourSurvole = survol !== null ? ind.jours[survol] : null;

  return (
    <section className="pulse-panel p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-headline-sm text-headline-sm text-ink">Alertes par jour · 30 jours</h2>
        <div className="flex flex-wrap gap-3 text-12 text-ink-dim">
          {SEVERITY_ORDER.map((s) => (
            <span key={s} className="inline-flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-sm ${severityFond[s]}`} />
              {severityLabels[s]}
            </span>
          ))}
        </div>
      </div>

      <div className="flex h-40 items-end gap-[3px]" onMouseLeave={() => setSurvol(null)}>
        {ind.jours.map((jour, i) => (
          <div
            key={jour.date}
            className="group flex h-full min-w-0 flex-1 cursor-default flex-col justify-end"
            onMouseEnter={() => setSurvol(i)}
            title={`${jour.date} — ${jour.total} alerte(s)`}
          >
            {jour.total === 0 ? (
              <div className="h-[2px] rounded-sm bg-line-soft" />
            ) : (
              <div
                className={`flex flex-col-reverse overflow-hidden rounded-sm ${
                  survol === i ? "opacity-100" : "opacity-85"
                }`}
                style={{ height: `${Math.max(4, (jour.total / ind.maxJour) * 100)}%` }}
              >
                {SEVERITY_ORDER.slice()
                  .reverse()
                  .map((s) =>
                    jour.parGravite[s] ? (
                      <div
                        key={s}
                        className={severityFond[s]}
                        style={{ flexGrow: jour.parGravite[s] }}
                      />
                    ) : null,
                  )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="mt-2 flex justify-between text-11 tabular-nums text-ink-faint">
        <span>{ind.jours[0].date.slice(5).split("-").reverse().join("/")}</span>
        <span className="text-ink-dim">
          {jourSurvole
            ? `${jourSurvole.date.split("-").reverse().join("/")} · ${jourSurvole.total} alerte(s)${
                jourSurvole.total
                  ? " — " +
                    SEVERITY_ORDER.filter((s) => jourSurvole.parGravite[s])
                      .map((s) => `${jourSurvole.parGravite[s]} ${severityLabels[s].toLowerCase()}`)
                      .join(", ")
                  : ""
              }`
            : "Survolez une barre pour le détail"}
        </span>
        <span>aujourd'hui</span>
      </div>

      {ind.horsFenetre > 0 && (
        <p className="mt-2 text-12 text-ink-faint">
          {ind.horsFenetre} alerte(s) antérieure(s) à la fenêtre de 30 jours ne figurent pas sur ce graphique.
        </p>
      )}
    </section>
  );
}

function EntityCard({ summary, delayMs }: { summary: EntitySummaryApi; delayMs: number }) {
  const typeEntries = Object.entries(summary.counts_by_type).sort((a, b) => b[1] - a[1]);

  return (
    <div className="pulse-panel stagger-in p-4" style={{ animationDelay: `${delayMs}ms` }}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-headline-sm text-headline-sm text-ink">{summary.entity_name}</h3>
        <span className="font-mono-data text-headline-sm tabular-nums text-signal">
          {summary.total_detections}
        </span>
      </div>

      {summary.total_detections === 0 ? (
        <p className="text-body-sm text-ink-dim">Aucune détection rattachée pour l'instant.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {SEVERITY_ORDER.filter((s) => summary.counts_by_severity[s]).map((severity) => (
              <div key={severity} className="flex items-center gap-1">
                <SeverityBadge severity={severity} />
                <span className="font-mono-data text-body-sm text-ink-dim">
                  {summary.counts_by_severity[severity]}
                </span>
              </div>
            ))}
          </div>

          {typeEntries.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {typeEntries.map(([type, count]) => (
                <span key={type} className="rounded bg-panel-raised px-2 py-1 text-12 text-ink">
                  {detectionTypeLabel(type)}: {count}
                </span>
              ))}
            </div>
          )}

          <div className="space-y-1 border-t border-line-soft pt-2">
            {summary.recent_detections.slice(0, 5).map((detection) => (
              <div key={detection.id} className="flex items-center justify-between gap-2 text-body-sm">
                <div className="flex min-w-0 items-center gap-2">
                  <SeverityBadge severity={detection.severity} />
                  <MaskedValue value={detection.value_masked} />
                </div>
                <span className="shrink-0 text-11 text-ink-faint">{dateHeure(detection.created_at)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function Statistics() {
  // ⚠️ CETTE PAGE EST OUVERTE A LA DIRECTION, PAS SES DEUX MOITIES.
  // `/api/stats/entities` est en TOUS, mais le détail des indicateurs est
  // recalculé à partir de la LISTE DES ALERTES, qui est en
  // PEUT_TRAITER_LES_ALERTES. Sans cette garde, le RSSI recevait un 403 au
  // milieu de l'une de ses deux seules pages : la requête partait, échouait, et
  // un message d'erreur technique s'affichait à la place des chiffres. On ne
  // la lance plus — une page tronquée mais cohérente vaut mieux qu'une page
  // complète à moitié en panne.
  const { user } = useAuth();
  const voitLesAlertes = peutAcceder(user?.role, "alertes");

  const entitesReq = useRequete(async () => (await statsApi.entities()).entities, []);
  const alertesReq = useRequete(() => chargerToutesLesAlertes(), [], { actif: voitLesAlertes });
  const entities: EntitySummaryApi[] | null = entitesReq.donnees;
  const entitiesError = entitesReq.erreur;
  const charge: ChargeAlertes | null = alertesReq.donnees;
  const alertesError = alertesReq.erreur;

  const ind = useMemo(() => (charge ? calculerIndicateurs(charge.alertes) : null), [charge]);
  const tronque = charge !== null && charge.alertes.length < charge.total;

  return (
    <AppLayout title="Statistiques">
      <p className="mb-4 max-w-3xl text-body-sm text-ink-dim">
        {voitLesAlertes
          ? "Indicateurs calculés sur l'ensemble des alertes, puis le détail des détections rattachées à chaque organisation surveillée."
          : "Détail des détections rattachées à chaque organisation surveillée."}
      </p>

      {alertesError && (
        <p className="mb-4 rounded border border-critical/40 bg-critical-dim/30 p-3 text-body-sm text-critical">
          Impossible de charger les alertes : {alertesError}
        </p>
      )}

      {!voitLesAlertes && (
        <p className="mb-4 rounded border border-line bg-panel-raised/60 p-3 text-body-sm text-ink-dim">
          Le détail des alertes n&apos;est pas dans votre périmètre. Les chiffres ci-dessous
          portent sur les organisations surveillées.
        </p>
      )}

      {voitLesAlertes && !charge && !alertesError && (
        <div className="pulse-panel mb-4 flex items-center justify-center gap-2 p-8 text-ink-dim">
          <Icon name="progress_activity" className="animate-spin" />
          Calcul des indicateurs…
        </div>
      )}

      {charge && ind && (
        <div className="mb-6 space-y-4">
          {tronque && (
            <p className="rounded border border-warn/40 bg-warn-dim/30 p-3 text-body-sm text-warn">
              Indicateurs calculés sur les {charge.alertes.length} alertes les plus récentes sur {charge.total} :
              les chiffres ci-dessous ne portent pas sur tout l'historique.
            </p>
          )}

          <div className="grid grid-cols-1 gap-gutter sm:grid-cols-2 xl:grid-cols-4">
            <CarteIndicateur
              libelle="Alertes"
              valeur={String(charge.alertes.length)}
              detail={
                SEVERITY_ORDER.filter((s) => ind.parGravite[s])
                  .map((s) => `${ind.parGravite[s]} ${severityLabels[s].toLowerCase()}`)
                  .join(" · ") || "aucune alerte"
              }
            />
            <CarteIndicateur
              libelle="Ouvertes"
              valeur={String(ind.ouvertes)}
              detail="en attente de traitement"
              ton={ind.ouvertes > 0 ? "text-warn" : "text-ink"}
            />
            <CarteIndicateur
              libelle="Délai médian de traitement"
              valeur={ind.delaiMedianMs === null ? "—" : formatDuree(ind.delaiMedianMs)}
              detail={
                ind.delaisMesures === 0
                  ? "aucune résolution datée pour l'instant"
                  : `de la création à la résolution, sur ${ind.delaisMesures} alerte(s)`
              }
            />
            <CarteIndicateur
              libelle="Faux positifs"
              valeur={String(ind.fauxPositifs)}
              detail={
                ind.resolues === 0
                  ? "aucune alerte résolue"
                  : `${Math.round((ind.fauxPositifs / ind.resolues) * 100)} % des ${ind.resolues} résolue(s)`
              }
            />
          </div>

          <HistogrammeJournalier ind={ind} />
        </div>
      )}

      <h2 className="mb-1 font-headline-sm text-headline-sm text-ink">Par organisation</h2>
      <p className="mb-3 text-body-sm text-ink-dim">
        Détections rattachées à chaque organisation surveillée par ses sélecteurs (domaine, email, raison
        sociale).
      </p>

      {entitiesError && (
        <p className="mb-4 rounded border border-critical/40 bg-critical-dim/30 p-3 text-body-sm text-critical">
          Impossible de charger les statistiques par organisation : {entitiesError}
        </p>
      )}

      {entities === null && !entitiesError && (
        <div className="pulse-panel flex items-center justify-center gap-2 p-8 text-ink-dim">
          <Icon name="progress_activity" className="animate-spin" />
          Chargement…
        </div>
      )}

      {entities !== null && entities.length === 0 && (
        <div className="pulse-panel p-8 text-center text-ink-dim">
          Aucune organisation active. Déclarez-en une depuis{" "}
          <Link to="/entities" className="text-signal hover:underline">
            Organisations
          </Link>
          .
        </div>
      )}

      {entities !== null && entities.length > 0 && (
        <div className="grid grid-cols-1 items-start gap-gutter lg:grid-cols-2">
          {entities.map((summary, i) => (
            <EntityCard key={summary.entity_id} summary={summary} delayMs={i * 60} />
          ))}
        </div>
      )}
    </AppLayout>
  );
}
