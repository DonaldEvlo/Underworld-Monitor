import { useCallback, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/auth-context";
import { useEscapeKey } from "../../hooks/useEscapeKey";
import { useSidebarReduite } from "../../hooks/useSidebarReduite";
import { peutAcceder } from "../../lib/roles";
import { Icon } from "../ui/Icon";
import { ClocheAlertes, EtatPlateforme } from "./IndicateursBandeau";

interface TopBarProps {
  title: string;
  searchPlaceholder?: string;
  /** Valeur du champ de recherche. Fourni par la page qui sait quoi filtrer. */
  searchValue?: string;
  /** Absent = la page n'implemente pas la recherche : le champ est alors
   * rendu inerte et grise, plutot que de laisser croire qu'il fonctionne. */
  onSearchChange?: (value: string) => void;
  /** Ouvre le tiroir de navigation. Le bouton n'apparait que sous 1024px,
   * ou la barre laterale est escamotee (voir AppLayout). */
  onOpenSidebar?: () => void;
  children?: ReactNode;
}

export function TopBar({
  title,
  searchPlaceholder,
  searchValue,
  onSearchChange,
  onOpenSidebar,
  children,
}: TopBarProps) {
  const reduite = useSidebarReduite();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  // Échap ferme le menu, comme le panneau d'état et le tiroir de navigation.
  const fermerMenu = useCallback(() => setMenuOpen(false), []);
  useEscapeKey(menuOpen, fermerMenu);

  function handleLogout() {
    logout();
    void navigate("/login", { replace: true });
  }

  return (
    <header
      // ⚠️ Le bandeau est calé sur la largeur de la barre latérale, comme le
      // contenu : l'oublier laissait un décrochement de 190 px entre le menu
      // réduit et le titre de page.
      className={`fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between gap-3 border-b border-line bg-panel/80 px-4 backdrop-blur-sm transition-[left] duration-200 md:px-6 ${
        reduite ? "lg:left-[68px]" : "lg:left-64"
      }`}
    >
      <div className="flex min-w-0 items-center gap-3 md:gap-6">
        {onOpenSidebar && (
          <button
            type="button"
            onClick={onOpenSidebar}
            title="Ouvrir la navigation"
            aria-label="Ouvrir la navigation"
            className="rounded-md p-1.5 text-ink-dim transition-all hover:bg-panel-raised hover:text-signal lg:hidden"
          >
            <Icon name="menu" />
          </button>
        )}
        <span className="whitespace-nowrap font-mono-label text-mono-label uppercase tracking-widest text-ink-dim">
          {title}
        </span>
        {searchPlaceholder && (
          <div className="relative hidden w-full max-w-96 md:block">
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-18 text-ink-faint" />
            <input
              type="search"
              aria-label={searchPlaceholder}
              placeholder={searchPlaceholder}
              value={searchValue ?? ""}
              onChange={(e) => onSearchChange?.(e.target.value)}
              disabled={!onSearchChange}
              title={onSearchChange ? undefined : "Recherche non disponible sur cette page"}
              className="w-full rounded-md border border-line bg-panel-sunken py-1.5 pl-10 pr-4 font-mono-data text-mono-data text-ink outline-none transition-all placeholder:text-ink-faint focus:border-signal/50 focus:ring-1 focus:ring-signal/20 disabled:cursor-not-allowed disabled:opacity-40"
            />
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {children}
        {/* ⚠️ Ces deux boutons ne faisaient RIEN (aucun gestionnaire de clic)
            jusqu'au 2026-09-29. Affichés seulement si le rôle peut lire leurs
            données : le RSSI recevrait sinon des 403 (alertes et planification
            sont hors de son périmètre). */}
        {peutAcceder(user?.role, "alertes") && <ClocheAlertes />}
        {peutAcceder(user?.role, "corpus") && <EtatPlateforme />}
        <div className="mx-1 h-6 w-[1px] bg-line" />
        <div className="relative">
          <button
            onClick={() => setMenuOpen((o) => !o)}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-label="Menu du compte"
            className="flex items-center gap-2 rounded-md p-1.5 text-ink-dim transition-all hover:bg-panel-raised hover:text-signal"
          >
            <Icon name="account_circle" />
            {user && (
              <span className="whitespace-nowrap font-mono-label text-mono-label text-ink-dim">
                {user.username}
              </span>
            )}
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full z-50 mt-3 w-48 rounded-lg border border-line bg-panel-sunken p-1.5 shadow-2xl">
                <button
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-body-sm text-on-surface transition-colors hover:bg-error/15 hover:text-error"
                >
                  <Icon name="logout" className="text-18" />
                  Se déconnecter
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
