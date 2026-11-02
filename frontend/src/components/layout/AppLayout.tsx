import { useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useSidebarReduite } from "../../hooks/useSidebarReduite";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

interface AppLayoutProps {
  title: string;
  searchPlaceholder?: string;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  children: ReactNode;
}

/** Gabarit applicatif.
 *
 * Pense pour un poste de travail (>= 1024px) : la barre laterale y est
 * toujours visible et le contenu decale de sa largeur. En dessous de ce seuil
 * -- portable 13", fenetre reduite, projection -- elle devient
 * un tiroir escamotable ouvert par le bouton du header, pour ne pas amputer
 * la zone de travail. Ce n'est pas une refonte mobile : l'outil reste concu
 * pour un grand ecran, on garantit seulement qu'il ne casse pas en dessous. */
export function AppLayout({
  title,
  searchPlaceholder,
  searchValue,
  onSearchChange,
  children,
}: AppLayoutProps) {
  const location = useLocation();
  // ⚠️ Le décalage du contenu DOIT suivre la largeur de la barre, sinon la
  // page laisse une bande vide de 190 px (ou, à l'inverse, passe sous le
  // menu). C'est la raison pour laquelle l'état est partagé et non local à
  // la barre.
  const reduite = useSidebarReduite();

  // Naviguer referme le tiroir : sur ecran etroit il recouvre le contenu, le
  // laisser ouvert masquerait la page qu'on vient d'ouvrir. On derive l'etat
  // du chemin courant (remise a false quand pathname change) plutot que de le
  // corriger apres coup dans un effet, qui provoquait un rendu en cascade :
  // ouvert -> navigation -> rendu avec tiroir encore ouvert -> effet -> rendu.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [drawerPath, setDrawerPath] = useState(location.pathname);
  if (drawerPath !== location.pathname) {
    setDrawerPath(location.pathname);
    setSidebarOpen(false);
  }

  return (
    <div className="void-texture min-h-screen bg-background font-body-md text-on-background">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <TopBar
        title={title}
        searchPlaceholder={searchPlaceholder}
        searchValue={searchValue}
        onSearchChange={onSearchChange}
        onOpenSidebar={() => setSidebarOpen(true)}
      />
      <main
        className={`mt-14 min-h-[calc(100vh-3.5rem)] p-4 transition-[margin] duration-200 md:p-6 ${
          reduite ? "lg:ml-[68px]" : "lg:ml-64"
        }`}
      >
        {children}
      </main>
    </div>
  );
}
