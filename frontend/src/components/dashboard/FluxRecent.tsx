import { Link } from "react-router-dom";
import type { DetectionListItem } from "../../api/detections";
import { MaskedValue } from "../ui/MaskedValue";
import { detectionTypeLabels } from "../../lib/taxonomy";
import { dateHeure, heure } from "../../lib/format";

interface FluxRecentProps {
  detections: DetectionListItem[];
  documentCount: number | null;
  detectionTotal: number | null;
}


function libelleType(type: string): string {
  return detectionTypeLabels[type as keyof typeof detectionTypeLabels] ?? type;
}

/** Ce qui est arrive depuis la derniere fois qu'on a regarde.
 *
 * ⚠️ Les valeurs sont MASQUEES, comme partout ailleurs : la valeur brute
 * n'existe ni en base, ni dans un log, ni dans un export. `MaskedValue` est le
 * seul composant autorise a les afficher.
 */
export function FluxRecent({ detections, documentCount, detectionTotal }: FluxRecentProps) {
  return (
    <section className="rounded-[18px] border border-line bg-panel p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">
          Nouveau depuis 24 h
        </h2>
        <Link to="/detections" className="font-mono-label text-11 text-signal hover:underline">
          tout voir
        </Link>
      </div>

      {detections.length === 0 ? (
        <p className="mt-3 text-body-sm text-ink-dim">Aucune détection récente.</p>
      ) : (
        <div className="mt-2.5 flex flex-col gap-1.5">
          {detections.map((d) => (
            <div
              key={d.id}
              className="grid grid-cols-[3.2rem_1fr_auto] items-center gap-2.5 font-mono-data text-11"
            >
              <span className="text-ink-faint" title={dateHeure(d.created_at)}>
                {heure(d.created_at)}
              </span>
              <span className="truncate text-ink">
                <MaskedValue value={d.value_masked} />
              </span>
              <span className="text-right text-ink-dim">{libelleType(d.type)}</span>
            </div>
          ))}
        </div>
      )}

      {/* La volumetrie vit ICI, en pied de panneau, et nulle part ailleurs. */}
      <div className="mt-3 flex justify-between border-t border-line-soft pt-2.5 font-mono-label text-11 text-ink-faint">
        <span>corpus {documentCount?.toLocaleString("fr-FR") ?? "—"} documents</span>
        <span>{detectionTotal?.toLocaleString("fr-FR") ?? "—"} détections</span>
      </div>
    </section>
  );
}
