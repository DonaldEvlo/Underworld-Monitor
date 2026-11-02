import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../../context/auth-context";
import { useEscapeKey } from "../../hooks/useEscapeKey";
import { basculerSidebarReduite, useSidebarReduite } from "../../hooks/useSidebarReduite";
import { useVeilleBadges } from "../../hooks/useVeilleBadges";
import { prechargerCartographie } from "../../lib/prechargement";
import { libelleRole, peutAcceder, perimetreDeRoute } from "../../lib/roles";
import { Icon } from "../ui/Icon";
import { LogoFaille } from "../ui/LogoFaille";

interface SidebarProps {
  /** Ouverture du tiroir sous 1024px. Sans effet au-dessus : la barre y est
   * toujours affichee (voir AppLayout). */
  open: boolean;
  onClose: () => void;
}

/** Compteur affiche en pastille. Jamais une valeur figee : le nombre vient de
 * `/api/stats/activity`, et la pastille disparait quand il vaut zero. */
type Compteur = "alertes_ouvertes" | "entites_sans_selecteur" | "sources_en_echec";

interface Entree {
  to: string;
  label: string;
  icon: string;
  compteur?: Compteur;
  /** `warn` = ce nombre decrit un trou dans la veille, pas une charge de travail. */
  ton?: "signal" | "warn";
}

/** Navigation en cinq groupes, ordonnes par moment d'usage.
 *
 * ⚠️ QUATORZE ENTREES DE MEME POIDS obligeaient a relire le menu en entier a
 * chaque fois, et aucun etat n'y remontait : ni ce qui est urgent, ni ce qui
 * est en panne. Le regroupement n'est pas cosmetique — « Traiter » est ce
 * qu'un analyste ouvre chaque matin, « Systeme » ce qu'il regle une fois par
 * mois. Les libelles anglais restants (Dashboard, Alerts, Statistics) passent
 * en francais, comme le reste de l'interface et les rapports produits.
 */
const GROUPES: { label: string; items: Entree[] }[] = [
  {
    label: "Traiter",
    items: [
      {
        to: "/",
        // ⚠️ « Poste de veille » est l'ecran de l'ANALYSTE, pas une vue de
        // direction : il interroge alertes, documents, detections, entites et
        // sources. Le classer « agrege » envoyait un RSSI sur un tableau de
        // bord dont six appels sur sept repondaient 403 — mesure au
        // navigateur. Le RSSI atterrit sur la Cartographie (voir App.tsx).
        label: "Poste de veille",
        icon: "monitor_heart",
      },
      {
        to: "/alerts",
        label: "Alertes",
        icon: "notifications_active",
        compteur: "alertes_ouvertes",
        ton: "signal",
      },
    ],
  },
  {
    label: "Périmètre",
    items: [
      // Le compteur porte les organisations SANS SELECTEUR : elles ne peuvent
      // structurellement jamais produire d'alerte.
      {
        to: "/entities",
        label: "Organisations",
        icon: "shield_person",
        compteur: "entites_sans_selecteur",
        ton: "warn",
      },
      {
        to: "/sources",
        label: "Sources",
        icon: "source",
        compteur: "sources_en_echec",
        ton: "warn",
      },
      { to: "/watchlist", label: "Watchlist", icon: "visibility" },
    ],
  },
  {
    label: "Corpus",
    items: [
      { to: "/documents", label: "Documents", icon: "description" },
      { to: "/detections", label: "Détections", icon: "policy" },
      // ⚠️ Cherche dans le corpus DÉJÀ COLLECTÉ. À ne pas confondre avec
      // « Découvrir des sources », qui interroge des moteurs .onion pour
      // trouver de NOUVELLES SOURCES.
      { to: "/lookup", label: "Rechercher une valeur", icon: "manage_search" },
    ],
  },
  {
    label: "Analyse",
    items: [
      { to: "/gouvernance", label: "Gouvernance", icon: "policy" },
      { to: "/perimetre", label: "Périmètre surveillé", icon: "shield_person" },
      { to: "/cartographie", label: "Cartographie", icon: "public" },
      { to: "/fiabilite", label: "Fiabilité", icon: "fact_check" },
      { to: "/statistics", label: "Statistiques", icon: "query_stats" },
    ],
  },
  {
    label: "Système",
    items: [
      { to: "/collecte", label: "Collecte", icon: "cloud_download" },
      { to: "/planification", label: "Planification", icon: "schedule" },
      { to: "/recherche", label: "Découvrir des sources", icon: "travel_explore" },
      { to: "/settings", label: "Modèle LLM", icon: "smart_toy" },
      { to: "/comptes", label: "Comptes", icon: "groups" },
      { to: "/telegram", label: "Compte Telegram", icon: "send" },
    ],
  },
];

/** Bouton rond de repli/deploiement, avec son libelle en pastille au survol.
 *
 * ⚠️ POURQUOI UNE INFOBULLE MAISON ET NON `title=""`. L'infobulle native met
 * ~1 s a apparaitre, se place ou le systeme veut et ne se style pas : sur un
 * bouton sans libelle, c'est la seule chose qui dit ce qu'il fait, elle ne
 * peut pas etre approximative. Celle-ci apparait immediatement, a cote du
 * bouton, dans la typographie du produit.
 *
 * ⚠️ Elle reste `aria-hidden` : le nom accessible vient d'`aria-label` sur le
 * bouton. Deux sources annonceraient le libelle deux fois au lecteur d'ecran.
 *
 * ⚠️ `pointer-events-none` sur la pastille : sans cela elle s'interpose sous
 * le curseur quand elle s'affiche a droite du bouton, ce qui coupe le survol
 * et la fait clignoter.
 */
function BasculeReduction({ reduite }: { reduite: boolean }) {
  const libelle = reduite ? "Ouvrir la barre latérale" : "Fermer la barre latérale";
  return (
    <div className="group/bascule relative hidden shrink-0 lg:block">
      <button
        type="button"
        onClick={basculerSidebarReduite}
        aria-label={libelle}
        aria-pressed={reduite}
        className="flex h-8 w-8 items-center justify-center rounded-full border border-transparent text-ink-faint transition-colors duration-150 hover:border-line hover:bg-panel-raised hover:text-ink focus-visible:border-line focus-visible:bg-panel-raised focus-visible:text-ink focus-visible:outline-none"
      >
        <Icon
          name={reduite ? "left_panel_open" : "left_panel_close"}
          className="text-18"
        />
      </button>
      {/* ⚠️ PLACEMENT DICTÉ PAR L'EMPILEMENT, pas par l'esthétique. Posée à
          droite du bouton en mode déployé, la pastille passait DERRIÈRE le
          bandeau supérieur : la barre est en `lg:z-30`, le bandeau en `z-40`,
          et un `z-50` posé à l'intérieur de la barre ne peut pas en sortir —
          il est enfermé dans son contexte d'empilement. Constaté à l'image,
          pas déduit.
          → déployé : SOUS le bouton, aligné à droite, donc entièrement dans
            la barre ;
          → réduit : à DROITE, seul placement possible sur 68 px — et là c'est
            sans danger, le bouton est à ~80 px du haut, sous le bandeau. */}
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute z-50 whitespace-nowrap rounded-full border border-line bg-panel-raised px-3 py-1.5 font-body-md text-12 font-medium text-ink opacity-0 shadow-lg transition-all duration-150 group-hover/bascule:translate-x-0 group-hover/bascule:translate-y-0 group-hover/bascule:opacity-100 ${
          reduite
            ? "left-full top-1/2 ml-2 -translate-y-1/2 translate-x-1"
            : "right-0 top-full mt-2 translate-y-1"
        }`}
      >
        {libelle}
      </span>
    </div>
  );
}

/** Ce que compte la pastille. Extrait pour être réutilisé par l'infobulle du
 * lien en mode réduit : un point sans explication ne dit pas ce qu'il compte. */
function infobulleCompteur(compteur?: Compteur): string {
  if (compteur === "entites_sans_selecteur")
    return "Organisations sans sélecteur : elles ne peuvent jamais alerter";
  if (compteur === "sources_en_echec")
    return "Sources dont la dernière collecte a échoué";
  return "Alertes ouvertes";
}

// ⚠️ Position de défilement du menu, conservée HORS du composant. Chaque page
// rend son propre `AppLayout`, donc la barre latérale est recréée à chaque
// navigation : cliquer une entrée du bas (Système) faisait remonter le menu
// tout en haut, et l'entrée choisie sortait de l'écran.
let defilementMenu = 0;

export function Sidebar({ open, onClose }: SidebarProps) {
  const location = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const [indicator, setIndicator] = useState<{ top: number; height: number } | null>(null);
  const activite = useVeilleBadges();
  const { user } = useAuth();
  // ⚠️ Le mode réduit ne concerne QUE le poste de travail (>= 1024px). Sous ce
  // seuil la barre est déjà un tiroir escamotable : y superposer un mode
  // icônes donnerait deux mécanismes pour le même besoin, et le tiroir
  // s'ouvrirait sur une colonne de pictogrammes sans libellé.
  // ⚠️ Un groupe dont toutes les entrees sont masquees disparait AUSSI :
  // laisser « Systeme » avec son filet et aucune ligne afficherait une
  // rubrique vide, ce qui se lit comme une panne.
  //
  // ⚠️ Ce filtre est de l'AFFICHAGE, pas de la securite. La garde est serveur
  // (`api/deps.exige_role`, 403). Un utilisateur qui taperait l'URL a la main
  // verrait la page, et ses appels echoueraient — c'est le comportement
  // attendu, pas une faille.
  const groupesVisibles = GROUPES.map((groupe) => ({
    ...groupe,
    items: groupe.items.filter((item) => {
      const perimetre = perimetreDeRoute(item.to);
      // Une entree pointant une route non declaree est masquee, jamais
      // affichee par defaut : elle menerait a « page introuvable ».
      return perimetre !== undefined && peutAcceder(user?.role, perimetre);
    }),
  })).filter((groupe) => groupe.items.length > 0);

  const reduiteReglage = useSidebarReduite();
  const reduite = reduiteReglage && !open;

  // Le tiroir se ferme a Echap comme toute surface qui recouvre le contenu.
  useEscapeKey(open, onClose);

  // Avant la première peinture : restaurer après coup ferait voir le saut.
  useLayoutEffect(() => {
    if (navRef.current) navRef.current.scrollTop = defilementMenu;
  }, []);

  useLayoutEffect(() => {
    const active = navRef.current?.querySelector<HTMLElement>("a[aria-current='page']");
    if (active) {
      setIndicator({ top: active.offsetTop, height: active.offsetHeight });
    }
  }, [location.pathname]);

  return (
    <>
      {/* Voile : uniquement sous lg, ou le tiroir recouvre le contenu. */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        className={`fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-line bg-panel-sunken transition-[transform,width] duration-200 lg:z-30 lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        } ${reduite ? "w-64 lg:w-[68px]" : "w-64"}`}
      >
      <div
        className={`border-b border-line-soft ${reduite ? "px-3 py-5" : "px-6 py-7"}`}
      >
        <div className={`flex items-center ${reduite ? "justify-center" : "gap-2.5"}`}>
          <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-signal/12">
            <LogoFaille size={19} className="text-signal" />
          </span>
          {!reduite && (
            <span className="font-display text-17 font-bold tracking-tight text-ink">
              Underworld Monitor
            </span>
          )}
        </div>
        {/* ⚠️ La bascule est sur la LIGNE DU DESSOUS, pas à côté du titre.
            Mesuré : sur 256 px, logo + bouton ne laissent que ~134 px au
            titre, qui sortait tronqué (« Underworld M… »). Un nom de produit
            rogné pour loger un bouton, c'est le bouton qu'il faut déplacer.

            ⚠️ Masquée sous lg : la barre y est un tiroir escamotable, pas une
            colonne fixe — replier un tiroir n'a pas de sens et doublerait la
            fermeture existante.

            En HAUT et non en pied : c'est là qu'on la cherche, et c'est le
            seul endroit visible quelle que soit la position de défilement du
            menu. */}
        <div
          className={`flex items-center ${
            reduite ? "mt-3 justify-center" : "mt-1.5 justify-between"
          }`}
        >
          {!reduite && (
            <span className="font-caption text-caption text-ink-faint">Command Center</span>
          )}
          <BasculeReduction reduite={reduite} />
        </div>
      </div>
      <nav
        ref={navRef}
        onScroll={(e) => {
          defilementMenu = e.currentTarget.scrollTop;
        }}
        className="custom-scrollbar relative flex-1 overflow-y-auto px-3 py-3"
      >
        {indicator && (
          <span
            className="absolute left-0 w-[3px] rounded-r bg-signal shadow-signal-glow transition-all duration-300 ease-out"
            style={{ top: indicator.top, height: indicator.height }}
          />
        )}
        {groupesVisibles.map((groupe) => (
          <div key={groupe.label} className="mb-1.5">
            {/* ⚠️ Le titre de groupe ne se tronque pas : « Périmètre » sur
                68 px devient illisible. En mode réduit il laisse place à un
                filet, qui conserve le REGROUPEMENT — c'est lui qui porte
                l'information, pas le mot. */}
            {reduite ? (
              <div className="mx-auto my-2 h-px w-6 bg-line-soft" aria-hidden="true" />
            ) : (
              <p className="px-3.5 pb-1 pt-3 font-caption text-caption text-ink-faint">
                {groupe.label}
              </p>
            )}
            {groupe.items.map((item) => {
              const valeur = item.compteur ? (activite?.[item.compteur] ?? 0) : 0;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  // Le globe pèse ~2 Mo : son téléchargement part au survol,
                  // pas au clic.
                  onMouseEnter={item.to === "/cartographie" ? prechargerCartographie : undefined}
                  onFocus={item.to === "/cartographie" ? prechargerCartographie : undefined}
                  // En mode réduit, l'infobulle native EST le libellé : sans
                  // elle une colonne d'icônes n'est pas utilisable.
                  title={
                    reduite
                      ? valeur > 0
                        ? `${item.label} — ${valeur} (${infobulleCompteur(item.compteur)})`
                        : item.label
                      : undefined
                  }
                  className={({ isActive }) =>
                    `group relative flex items-center rounded-md py-2 transition-all duration-150 ${
                      reduite ? "justify-center px-0" : "gap-3 px-3.5"
                    } ${
                      isActive
                        ? "bg-signal/10 text-signal"
                        : "text-ink-dim hover:bg-panel-raised hover:text-ink"
                    }`
                  }
                >
                  <Icon
                    name={item.icon}
                    className="shrink-0 text-19 transition-transform duration-200 group-hover:scale-110"
                  />
                  {!reduite && (
                    <span className="min-w-0 flex-1 truncate font-body-md text-body-sm font-medium tracking-tight">
                      {item.label}
                    </span>
                  )}
                  {/* Pastille masquee a zero : « 0 organisation aveugle » est une
                      bonne nouvelle, pas une information a afficher en permanence. */}
                  {/* ⚠️ En mode réduit le NOMBRE ne tient pas : « 12 » sur une
                      colonne de 68 px déborde ou se tronque. Il devient un
                      point, qui conserve le seul message indispensable à ce
                      niveau de détail — « il y a quelque chose ici ». Le
                      compte exact reste lisible dans l'infobulle et sur la
                      page. Ne pas le remplacer par un nombre rogné : un
                      chiffre tronqué est pire qu'un point, il se lit comme
                      une valeur. */}
                  {valeur > 0 &&
                    (reduite ? (
                      <span
                        aria-hidden="true"
                        className={`absolute right-2 top-1.5 h-1.5 w-1.5 rounded-full ${
                          item.ton === "warn" ? "bg-warn" : "bg-signal"
                        }`}
                      />
                    ) : (
                      <span
                        className={`shrink-0 rounded-full border px-1.5 font-mono-label text-10 font-semibold tabular-nums ${
                          item.ton === "warn"
                            ? "border-warn/40 bg-warn-dim/50 text-warn"
                            : "border-signal/35 bg-signal/10 text-signal"
                        }`}
                        title={infobulleCompteur(item.compteur)}
                      >
                        {valeur}
                      </span>
                    ))}
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>
      <div className={`border-t border-line-soft py-5 ${reduite ? "px-2" : "px-4"}`}>
        <div
          className={`flex items-center rounded-md py-2 ${
            reduite ? "justify-center px-0" : "gap-3 px-3"
          }`}
          title={reduite ? (user?.username ?? "—") : undefined}
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-panel-raised">
            <Icon name="person" className="text-16 text-ink-dim" />
          </div>
          {!reduite && (
          <div className="overflow-hidden">
            {/* Le nom etait ecrit en dur (« Analyst_01 ») alors que la session
                porte le vrai compte : un outil qui journalise les acces ne peut
                pas afficher un utilisateur fictif. */}
            <p className="truncate font-mono-label text-mono-label text-ink">
              {user?.username ?? "—"}
            </p>
            <p className="text-10 uppercase tracking-wide text-ink-faint">
              {libelleRole(user?.role)}
            </p>
          </div>
          )}
        </div>
      </div>
      </aside>
    </>
  );
}
