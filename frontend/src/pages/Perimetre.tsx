import { useState } from "react";
import { Link } from "react-router-dom";
import {
  perimeterApi,
  type PerimeterAlertsResponse,
  type PerimeterGroup,
  type PerimeterOrg,
  type PerimeterState,
  type SeverityCounts,
} from "../api/perimeter";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { useAuth } from "../context/auth-context";
import { useRequete } from "../hooks/useRequete";
import { nomPays } from "../lib/alertes";
import { jour } from "../lib/format";
import { peutAcceder } from "../lib/roles";
import {
  credibilityLabel,
  severityFond,
  severityLabels,
  severityPuce,
  statusLabels,
} from "../lib/taxonomy";

const ETATS: Record<PerimeterState, { libelle: string; classe: string; aide: string }> = {
  a_traiter: {
    libelle: "à traiter",
    classe: "bg-critical/[0.14] text-critical",
    aide: "Au moins une alerte ouverte n'a pas encore été prise en charge.",
  },
  en_cours: {
    libelle: "en cours",
    classe: "bg-warn/[0.14] text-warn",
    aide: "Les alertes sont prises en charge par un analyste, pas encore résolues.",
  },
  traitee: {
    libelle: "traitée",
    classe: "bg-ok/[0.12] text-ok",
    aide: "Toutes les alertes de cette organisation ont été résolues.",
  },
  aucune_alerte: {
    libelle: "aucune alerte",
    classe: "bg-panel-raised text-ink-dim",
    aide: "Surveillée, rien n'a été détecté à ce jour.",
  },
  aveugle: {
    libelle: "angle mort",
    classe: "border border-warn/50 text-warn",
    aide: "Aucun sélecteur déclaré : cette organisation ne peut pas produire d'alerte.",
  },
  inactive: {
    libelle: "inactive",
    classe: "bg-panel-raised text-ink-faint",
    aide: "Surveillance suspendue.",
  },
};

const MOTIFS: Record<string, string> = {
  confirmed: "incident traité",
  false_positive: "faux positif",
  duplicate: "doublon",
  out_of_scope: "hors périmètre",
};

function Gravites({ c }: { c: SeverityCounts }) {
  const g = (["critical", "high", "medium"] as const).filter((s) => c[s] > 0);
  if (!g.length) return <span className="font-mono-data text-11 text-ink-faint">aucune alerte ouverte</span>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {g.map((s) => (
        <span key={s} className={`rounded-md border px-2 py-0.5 font-mono-data text-11 ${severityPuce[s]}`}>
          {c[s]} {severityLabels[s].toLowerCase()}
        </span>
      ))}
    </span>
  );
}

function Etat({ etat }: { etat: PerimeterState }) {
  const e = ETATS[etat];
  return (
    <span className={`shrink-0 rounded-md px-2 py-0.5 font-mono-label text-10 ${e.classe}`} title={e.aide}>
      {e.libelle}
    </span>
  );
}

function Faits({ o }: { o: PerimeterOrg }) {
  const faits = [nomPays(o.country), o.sector_label].filter(Boolean);
  return (
    <span className="text-body-sm text-ink-dim">
      {faits.join(" · ") || "pays et secteur non déclarés"}
      {o.sector_critical && (
        <span className="ml-1.5 rounded bg-warn/[0.14] px-1.5 py-0.5 font-mono-label text-10 text-warn">NIS2</span>
      )}
      {o.last_alert_date && (
        <span className="text-ink-faint"> · dernière alerte le {jour(o.last_alert_date)}</span>
      )}
    </span>
  );
}

/** Synthèse des alertes d'une organisation (et de ses filiales) : gravité,
 * crédibilité, traitement, résumé. Jamais les preuves. */
function AlertesOrganisation({ id, detail }: { id: string; detail: boolean }) {
  const req = useRequete(() => perimeterApi.alerts(id), [id]);
  const r: PerimeterAlertsResponse | null = req.donnees;
  if (req.erreur) return <p className="text-body-sm text-critical">Chargement impossible : {req.erreur}</p>;
  if (!r) return <p className="text-body-sm text-ink-dim">Chargement…</p>;
  if (!r.alerts.length) return <p className="text-body-sm text-ink-dim">Aucune alerte à ce jour.</p>;
  return (
    <div className="flex flex-col gap-1.5">
      {r.alerts.map((a) => {
        const contenu = (
          <>
            <span className={`w-1 self-stretch rounded ${severityFond[a.severity]}`} />
            <div className="min-w-0 flex-1 py-2">
              <p className="flex flex-wrap items-center gap-2 text-12">
                <span className="font-semibold text-ink">{a.organization}</span>
                <span className="text-ink-dim">{severityLabels[a.severity].toLowerCase()}</span>
                <span className="text-ink-faint">· {jour(a.alert_date)}</span>
                <span className="rounded-md bg-panel-raised px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
                  {a.resolution_reason ? MOTIFS[a.resolution_reason] ?? statusLabels[a.status] : statusLabels[a.status]}
                </span>
                {credibilityLabel(a.credibility_level) && (
                  <span className="font-mono-label text-10 text-ink-faint">
                    crédibilité : {credibilityLabel(a.credibility_level)?.toLowerCase()}
                  </span>
                )}
              </p>
              <p className="mt-0.5 line-clamp-2 text-body-sm text-ink-dim">
                {a.summary ?? "Résumé non encore rédigé."}
              </p>
            </div>
          </>
        );
        // Le RSSI n'ouvre pas le dossier (preuves, valeurs masquées, .onion) :
        // pas de lien qui mènerait à un refus.
        return detail ? (
          <Link
            key={a.id}
            to={`/alerts/${a.id}`}
            className="flex gap-2.5 rounded-lg border border-line bg-panel-sunken pr-3 transition-colors hover:border-signal/30"
          >
            {contenu}
          </Link>
        ) : (
          <div key={a.id} className="flex gap-2.5 rounded-lg border border-line bg-panel-sunken pr-3">
            {contenu}
          </div>
        );
      })}
    </div>
  );
}

function LigneOrganisation({
  o,
  ouverte,
  onBascule,
  detail,
  filiale = false,
}: {
  o: PerimeterOrg;
  ouverte: boolean;
  onBascule: () => void;
  detail: boolean;
  filiale?: boolean;
}) {
  return (
    <div className={filiale ? "ml-5 border-l-2 border-l-signal/25 pl-3" : ""}>
      <button
        onClick={onBascule}
        aria-expanded={ouverte}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 py-2 text-left"
      >
        <Icon name={ouverte ? "expand_less" : "expand_more"} className="text-16 text-ink-faint" />
        <span className={`font-semibold text-ink ${filiale ? "text-14" : "text-15"}`}>{o.name}</span>
        <Etat etat={o.state} />
        <span className="ml-auto">
          <Gravites c={o.open_by_severity} />
        </span>
        <span className="basis-full pl-7">
          <Faits o={o} />
        </span>
      </button>
      {ouverte && (
        <div className="pb-2 pl-7">
          <AlertesOrganisation id={o.id} detail={detail} />
        </div>
      )}
    </div>
  );
}

/**
 * Le périmètre surveillé, vu par le RSSI (2026-10-05).
 *
 * Le RSSI est le PROPRIÉTAIRE du périmètre : il doit savoir qui est surveillé,
 * où en est chaque organisation et ce qui reste à traiter, sans entrer dans
 * les preuves. Groupes et filiales sont présentés en arbre ; le groupe porte
 * le cumul de ses filiales.
 *
 * ⚠️ Faits de SYNTHÈSE seulement (voir pipeline/reporting/perimeter.py) :
 * aucune détection, aucune valeur, aucune adresse .onion, aucune victime hors
 * périmètre. Les alertes régionales (victimes non déclarées) n'y figurent pas.
 */
export function Perimetre() {
  const { user } = useAuth();
  const detail = peutAcceder(user?.role, "alertes");
  const req = useRequete(() => perimeterApi.get(), []);
  const [ouvertes, setOuvertes] = useState<Set<string>>(new Set());
  const [filiales, setFiliales] = useState<Set<string>>(new Set());

  function bascule(ensemble: Set<string>, id: string, set: (s: Set<string>) => void) {
    const s = new Set(ensemble);
    if (s.has(id)) s.delete(id);
    else s.add(id);
    set(s);
  }

  const p = req.donnees;
  return (
    <AppLayout title="Périmètre surveillé">
      <div className="flex flex-col gap-3.5">
        {req.erreur && (
          <p className="rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
            Impossible de charger le périmètre : {req.erreur}
          </p>
        )}
        {!p && !req.erreur && <p className="text-body-sm text-ink-dim">Chargement du périmètre…</p>}
        {p && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { n: p.organizations, l: "organisations surveillées", c: "text-ink" },
                { n: p.groups_with_subsidiaries, l: "groupes avec filiales", c: "text-ink" },
                { n: p.to_handle, l: "à traiter (alerte ouverte non prise en charge)", c: p.to_handle ? "text-critical" : "text-ink" },
                { n: p.blind, l: "angles morts (aucun sélecteur)", c: p.blind ? "text-warn" : "text-ink" },
              ].map((k) => (
                <div key={k.l} className="rounded-[18px] border border-line bg-panel px-4 py-3.5">
                  <p className={`font-mono-data text-30 tabular-nums ${k.c}`}>{k.n}</p>
                  <p className="text-body-sm text-ink-dim">{k.l}</p>
                </div>
              ))}
            </div>

            <p className="font-mono-label text-11 text-ink-faint">
              classées par urgence · les victimes non déclarées (alertes régionales) n&apos;appartiennent pas au
              périmètre et n&apos;apparaissent pas ici
            </p>

            {p.groups.length === 0 ? (
              <div className="rounded-[18px] border border-line bg-panel px-8 py-12 text-center text-body-sm text-ink-dim">
                Aucune organisation n&apos;est déclarée.
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {p.groups.map((g: PerimeterGroup) => (
                  <section key={g.id} className="rounded-[14px] border border-line bg-panel px-4 py-1.5">
                    <LigneOrganisation
                      o={g}
                      ouverte={ouvertes.has(g.id)}
                      onBascule={() => bascule(ouvertes, g.id, setOuvertes)}
                      detail={detail}
                    />
                    {g.subsidiaries.length > 0 && (
                      <div className="border-t border-line py-1.5">
                        <div className="flex flex-wrap items-center gap-3 pl-7">
                          <button
                            onClick={() => bascule(filiales, g.id, setFiliales)}
                            aria-expanded={filiales.has(g.id)}
                            className="flex items-center gap-1 font-mono-label text-11 text-signal"
                          >
                            <Icon name={filiales.has(g.id) ? "expand_less" : "expand_more"} className="text-14" />
                            {g.subsidiaries.length} filiale(s)
                          </button>
                          <span className="text-12 text-ink-dim">groupe entier :</span>
                          <Gravites c={g.group_open_by_severity} />
                          {detail && (
                            <Link
                              to={`/alerts?groupe=${g.id}`}
                              className="ml-auto font-mono-label text-11 text-ink-dim hover:text-ink"
                            >
                              alertes du groupe →
                            </Link>
                          )}
                        </div>
                        {filiales.has(g.id) &&
                          g.subsidiaries.map((f) => (
                            <LigneOrganisation
                              key={f.id}
                              o={f}
                              filiale
                              ouverte={ouvertes.has(f.id)}
                              onBascule={() => bascule(ouvertes, f.id, setOuvertes)}
                              detail={detail}
                            />
                          ))}
                      </div>
                    )}
                  </section>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </AppLayout>
  );
}
