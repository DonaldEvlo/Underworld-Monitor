import { alertsApi } from "../../../api/alerts";
import { Icon } from "../../ui/Icon";
import {
  severityCadre,
  severityFond,
  severityLabels,
  severityTexte,
  statusLabels,
  TLP_RAPPORT,
} from "../../../lib/taxonomy";
import type { AlertSeverity } from "../../../types/domain";
import type { ContexteDossier } from "./contexte";

/** Pourquoi CE niveau, en une phrase. Une gravité qu'on ne peut pas
 * expliquer est une gravité qu'on ne peut pas contester : la page n'en
 * recalcule rien, elle énonce la règle appliquée par le serveur. */
// ⚠️ Échelle du 2026-09-26 (phase 7) : la gravité mesure l'IMPACT. La
// confirmation par un tiers relève de la crédibilité, pas de la gravité —
// l'ancien texte l'invoquait encore, et affichait donc une règle fausse.
const REGLE_GRAVITE: Record<AlertSeverity, string> = {
  critical:
    "Secteur critique (administration, santé, finance, énergie ou transport) ET incident de moins de 30 jours : l'organisation a encore le temps d'agir.",
  high: "Secteur critique (administration, santé, finance, énergie ou transport, selon NIS2). Un incident de moins de 30 jours la rendrait critique.",
  medium:
    "Rattachée à une organisation surveillée, hors secteur critique (ou secteur inconnu).",
  low: "Ni rattachée à une organisation surveillée, ni confirmée. Le plancher de l'échelle.",
};

/** En-tête : sujet, gravité et sa règle, actions sur l'alerte. */
export function EnteteDossier({ c }: { c: ContexteDossier }) {
  const { alerte, sujet, domaine, enCours, telecharger, agir } = c;
  return (
    <>
      {/* ---- en-tête du dossier ---- */}
      <section
        className={`mb-3.5 flex flex-col gap-5 rounded-[18px] border bg-panel p-5 lg:flex-row ${severityCadre[alerte.severity]}`}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            <span
              className={`h-2 w-2 rounded-full ${severityFond[alerte.severity]} ${
                alerte.severity === "critical" ? "animate-pulse-critical" : ""
              }`}
            />
            <span
              className={`font-mono-label text-10 uppercase tracking-widest ${severityTexte[alerte.severity]}`}
            >
              Gravité {severityLabels[alerte.severity]}
            </span>
            <span className="rounded border border-line px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
              {statusLabels[alerte.status]}
            </span>
            {/* Consigne de diffusion (FIRST TLP 2.0) : le dossier et son
                rapport PDF ne s'adressent qu'à l'organisation victime. */}
            <span
              className="rounded bg-black px-1.5 py-0.5 font-mono-label text-10 font-bold text-[#FFC000]"
              title="Diffusion limitée à l'organisation destinataire, sur la base du besoin d'en connaître (FIRST TLP 2.0)."
            >
              {TLP_RAPPORT}
            </span>
          </div>

          <h1 className="mt-1.5 font-display text-headline-lg text-ink">{sujet}</h1>
          <p className="mt-0.5 font-mono-data text-mono-data text-ink-dim">
            {alerte.group_name ? `filiale du groupe ${alerte.group_name} · ` : ""}
            {domaine ? `${domaine} · ` : ""}journée du {alerte.alert_date} ·{" "}
            {alerte.detection_count} détections
          </p>
          <p className="mt-2.5 max-w-[80ch] text-body-sm text-ink-dim">
            {alerte.severity_origin === "analyst"
              ? `Gravité corrigée par ${alerte.override_by ?? "un analyste"} : ${alerte.override_reason ?? ""}`
              : REGLE_GRAVITE[alerte.severity]}
          </p>
        </div>

        <div className="flex w-full shrink-0 flex-col gap-2 lg:w-56">
          <button
            onClick={() => void telecharger("pdf", () => alertsApi.downloadReport(alerte.id))}
            disabled={enCours !== null}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-signal px-3 py-2.5 text-body-sm font-bold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {enCours === "pdf" && <Icon name="progress_activity" className="animate-spin text-16" />}
            {enCours === "pdf" ? "Rédaction du rapport…" : "Exporter le rapport PDF"}
          </button>
          <p className="text-center font-mono-label text-10 text-ink-dim">
            synthèse rédigée par le modèle · 20 s à 1 min 30
          </p>
          {/* Format d'échange d'un CERT : un CSV ou un PDF ne s'importe dans
              aucune plateforme de renseignement, un paquet STIX 2.1 oui. */}
          <button
            onClick={() => void telecharger("stix", () => alertsApi.downloadStix(alerte.id))}
            disabled={enCours !== null}
            title="Paquet STIX 2.1 importable dans MISP ou OpenCTI — marqué TLP:AMBER+STRICT"
            className="rounded-lg border border-line px-3 py-2 text-body-sm text-ink transition-colors hover:bg-panel-sunken"
          >
            Exporter en STIX 2.1
          </button>
          <p className="text-center font-mono-label text-10 text-ink-faint">
            TLP:AMBER+STRICT
          </p>
          <div className="mt-1 flex gap-2">
            <button
              disabled={enCours !== null || alerte.status === "acknowledged"}
              onClick={() =>
                void agir("ack", () => alertsApi.updateStatus(alerte.id, "acknowledged"))
              }
              className="flex-1 rounded-lg border border-line bg-panel-raised px-2 py-2 text-body-sm text-ink transition-colors hover:border-signal/40 disabled:opacity-40"
            >
              Acquitter
            </button>
            <button
              disabled={enCours !== null || alerte.status === "resolved"}
              onClick={() =>
                void agir("res", async () => {
                  await alertsApi.updateStatus(alerte.id, "resolved");
                  return alertsApi.triage(alerte.id, { resolution_reason: "confirmed" });
                })
              }
              className="flex-1 rounded-lg border border-line bg-panel-raised px-2 py-2 text-body-sm text-ink transition-colors hover:border-signal/40 disabled:opacity-40"
            >
              Résoudre
            </button>
          </div>
          {/* ⚠️ Un faux positif est une alerte CLOSE avec un motif distinct de
              « traitée ». Sans ce motif, écarter une fausse alerte et traiter un
              incident réel laissent le même état, et l'historique des faux
              positifs — seule matière permettant d'ajuster les seuils — est
              perdu. La première version posait le motif SANS clore l'alerte :
              elle restait « ouverte » (constaté le 2026-10-02). */}
          <button
            disabled={enCours !== null || alerte.resolution_reason === "false_positive"}
            onClick={() =>
              void agir("fp", async () => {
                await alertsApi.triage(alerte.id, { resolution_reason: "false_positive" });
                return alertsApi.updateStatus(alerte.id, "resolved");
              })
            }
            className="rounded-lg border border-line px-3 py-2 text-body-sm text-ink-dim transition-colors hover:text-ink disabled:opacity-40"
          >
            Marquer faux positif
          </button>
        </div>
      </section>
    </>
  );
}
