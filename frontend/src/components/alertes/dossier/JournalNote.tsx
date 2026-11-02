import { useState } from "react";
import { alertsApi } from "../../../api/alerts";
import { dateHeure } from "../../../lib/format";
import type { ContexteDossier } from "./contexte";

const MOTIFS: Record<string, string> = {
  confirmed: "traitée",
  false_positive: "faux positif",
  duplicate: "doublon",
  out_of_scope: "hors périmètre",
};

/** Journal de l'alerte, note d'analyste et rappel.
 *
 * ⚠️ La note était AFFICHÉE mais n'avait aucun champ de saisie : l'analyste
 * résolvait des alertes sans pouvoir dire ce qu'il avait vérifié (constaté le
 * 2026-10-02 sur 20 alertes résolues, 0 note). Une résolution sans note ne
 * prouve pas qu'une analyse a eu lieu.
 */
export function JournalNote({ c }: { c: ContexteDossier }) {
  const { alerte, agir, enCours } = c;
  const [note, setNote] = useState(alerte.analyst_note ?? "");
  const modifiee = note.trim() !== (alerte.analyst_note ?? "").trim();
  const close = alerte.status !== "open";

  return (
    <section className="pulse-panel p-4">
      <h2 className="font-display text-15 font-bold tracking-tight text-ink">
        Journal &amp; note
      </h2>
      <div className="mt-2.5 flex flex-col gap-2">
        {[
          ["créée", alerte.created_at],
          ["corroborée", alerte.corroborated_at],
          ["acquittée", alerte.acknowledged_at],
          ["résolue", alerte.resolved_at],
          ["rappel", alerte.reminded_at],
        ]
          .filter((l): l is [string, string] => Boolean(l[1]))
          .map(([libelle, quand]) => (
            <div key={libelle} className="grid grid-cols-[5.5rem_1fr] gap-2.5">
              <span className="font-mono-label text-10.5 text-ink-faint">{libelle}</span>
              <span className="font-mono-data text-11 text-ink">{dateHeure(quand)}</span>
            </div>
          ))}
        {alerte.resolution_reason && (
          <div className="grid grid-cols-[5.5rem_1fr] gap-2.5">
            <span className="font-mono-label text-10.5 text-ink-faint">motif</span>
            <span className="font-mono-data text-11 text-ink">
              {MOTIFS[alerte.resolution_reason] ?? alerte.resolution_reason}
            </span>
          </div>
        )}
      </div>

      <label htmlFor="note-analyste" className="mt-3 block font-mono-label text-10.5 text-ink-dim">
        Note d&apos;analyste — ce qui a été vérifié
      </label>
      <textarea
        id="note-analyste"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={4000}
        rows={4}
        placeholder="Ex. : adresse .onion ouverte dans Tor Browser, victime présente ; confirmé par un article de presse."
        className="mt-1 w-full resize-y rounded-xl border border-line bg-panel-sunken p-2.5 text-body-sm text-ink outline-none transition-colors focus:border-signal/60"
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          disabled={!modifiee || enCours !== null}
          onClick={() =>
            void agir("note", () =>
              alertsApi.triage(alerte.id, { analyst_note: note.trim() || null }),
            )
          }
          className="rounded-lg border border-line bg-panel-raised px-3 py-1.5 text-body-sm text-ink transition-colors hover:border-signal/40 disabled:opacity-40"
        >
          {enCours === "note" ? "Enregistrement…" : "Enregistrer la note"}
        </button>
        {close && (
          <button
            disabled={enCours !== null}
            onClick={() => void agir("rappel", () => alertsApi.remind(alerte.id))}
            className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim transition-colors hover:text-ink disabled:opacity-40"
            title="Remet l'alerte en « ouverte » sans en créer une nouvelle"
          >
            Rouvrir (rappel)
          </button>
        )}
      </div>
      <p className="mt-2 font-mono-label text-10 text-ink-faint">
        aucune donnée personnelle dans la note · la plateforme ne contacte jamais la victime
      </p>
    </section>
  );
}
