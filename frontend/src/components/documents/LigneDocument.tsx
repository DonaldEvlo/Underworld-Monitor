import type { DocumentListItem } from "../../api/documents";
import { dateHeure } from "../../lib/format";
import { Icon } from "../ui/Icon";
import { hrefSur } from "../../lib/liens";

/** Une ligne de la liste des documents ; un clic ouvre le détail. */
export function LigneDocument({
  doc,
  onOuvrir,
}: {
  doc: DocumentListItem;
  onOuvrir: (id: string) => void;
}) {
  return (
    <tr
      onClick={() => onOuvrir(doc.id)}
      className="group cursor-pointer transition-colors hover:bg-surface-container-high/50"
    >
      <td className="max-w-sm px-4 py-3">
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            <span className="truncate font-bold text-on-surface">{doc.title || "(sans titre)"}</span>
            {doc.matched_keywords && doc.matched_keywords.length > 0 && (
              <span
                title={`Mots-clés watchlist : ${doc.matched_keywords.join(", ")}`}
                className="flex shrink-0 items-center gap-1 rounded border border-tertiary/40 bg-tertiary-container/20 px-1.5 py-0.5 font-mono-data text-10 text-tertiary"
              >
                <Icon name="visibility" className="text-12" />
                {doc.matched_keywords.length}
              </span>
            )}
            {doc.mentioned_url_count > 0 && (
              <span
                title={`${doc.mentioned_url_count} lien(s) mentionné(s) dans le contenu`}
                className="flex shrink-0 items-center gap-1 rounded border border-info/40 bg-info-dim/40 px-1.5 py-0.5 font-mono-data text-10 text-info"
              >
                <Icon name="link" className="text-12" />
                {doc.mentioned_url_count}
              </span>
            )}
            {doc.content_locked && (
              <span
                title="Contenu verrouillé (mur « réagir pour voir »)"
                className="flex shrink-0 items-center gap-1 rounded border border-warn/40 bg-warn-dim/40 px-1.5 py-0.5 font-mono-data text-10 text-warn"
              >
                <Icon name="lock" className="text-12" />
              </span>
            )}
            {/* Un document écarté n'apparaît que si l'analyste a
                demandé à voir le bruit : le marquer évite de le
                confondre avec une annonce retenue. Le motif du
                classement est dans l'infobulle — un classement sans
                motif n'est pas contestable. */}
            {doc.announcement_class === "noise" && (
              <span
                title={`Écarté du périmètre${doc.announcement_reason ? ` : ${doc.announcement_reason}` : ""}`}
                className="shrink-0 rounded border border-outline-variant bg-surface-variant/40 px-1.5 py-0.5 font-mono-data text-10 text-on-surface-variant"
              >
                bruit
              </span>
            )}
          </div>
          <span className="truncate font-mono-label text-10 text-on-surface-variant">
            {doc.content_preview}
          </span>
        </div>
      </td>
      <td className="px-4 py-3 text-body-sm text-on-surface-variant">{doc.source_name ?? "—"}</td>
      <td className="px-4 py-3">
        <span className="rounded border border-outline-variant bg-surface-container-highest px-1.5 py-0.5 font-mono-data text-10 text-on-surface-variant">
          {doc.collector}
        </span>
      </td>
      <td className="px-4 py-3 text-body-sm text-on-surface-variant">{doc.author ?? "—"}</td>
      <td className="px-4 py-3 font-mono-data text-body-sm text-on-surface-variant">
        {dateHeure(doc.published_at)}
      </td>
      <td className="px-4 py-3 font-mono-data text-body-sm text-on-surface-variant">
        {dateHeure(doc.fetched_at)}
      </td>
      <td className="px-4 py-3 text-right">
        {/* ⚠️ Un `.onion` s'affiche mais ne se clique pas : il exige
            Tor, un lien ordinaire ne mène nulle part. Seules les
            sources en clair gardent un lien direct. */}
        {!doc.url.includes(".onion") && (
        <a
          href={hrefSur(doc.url)}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="Ouvrir l'URL source directement"
          className="inline-flex rounded border border-transparent p-1.5 text-on-surface-variant opacity-0 transition-all hover:border-primary/30 hover:bg-primary/20 hover:text-primary group-hover:opacity-100"
        >
          <Icon name="open_in_new" className="text-16" />
        </a>
        )}
      </td>
    </tr>
  );
}
