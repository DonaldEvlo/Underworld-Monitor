import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import { RequireAuth } from "./components/auth/RequireAuth";
import { Alerts } from "./pages/Alerts";
import { Collecte } from "./pages/Collecte";
import { Comptes } from "./pages/Comptes";
import { Dashboard } from "./pages/Dashboard";
import { DossierAlerte } from "./pages/DossierAlerte";
import { InvestigationAlerte } from "./pages/InvestigationAlerte";
import { Detections } from "./pages/Detections";
import { Documents } from "./pages/Documents";
import { Entities } from "./pages/Entities";
import { Fiabilite } from "./pages/Fiabilite";
import { Login } from "./pages/Login";
import { Lookup } from "./pages/Lookup";
import { NotFound } from "./pages/NotFound";
import { Recherche } from "./pages/Recherche";
import { Settings } from "./pages/Settings";
import { TelegramCompte } from "./pages/TelegramCompte";
import { Sources } from "./pages/Sources";
import { Planification } from "./pages/Planification";
import { Statistics } from "./pages/Statistics";
import { Gouvernance } from "./pages/Gouvernance";
import { Perimetre } from "./pages/Perimetre";
import { Watchlist } from "./pages/Watchlist";
import { chargerPageCartographie } from "./lib/prechargement";

// Chargee a la demande : la carte embarque three.js, qui pese a lui seul
// plus que tout le reste de l'application. En import statique, un analyste
// qui ouvre la page Documents payait 600 Ko de moteur 3D qu'il n'utilise
// pas. Mesure : bundle principal 2,26 Mo en import statique, 349 Ko en
// chargement differe (le globe part dans un morceau de 1,9 Mo a part).
// Même promesse que le préchargement au survol du menu (lib/prechargement) :
// un clic après survol ne retélécharge rien.
const Cartographie = lazy(() =>
  chargerPageCartographie().then((m) => ({ default: m.Cartographie })),
);


export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Le perimetre de chaque route est declare dans `lib/roles.ts` et
          applique par `RequireAuth` -> `GardeRole`. Une route ajoutee ici sans
          y etre declaree rend « page introuvable » : defaut sur, et bruyant. */}
      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/alerts" element={<RequireAuth><Alerts /></RequireAuth>} />
      {/* Le dossier : une alerte ne tient pas dans une ligne de tableau. */}
      <Route path="/alerts/:id" element={<RequireAuth><DossierAlerte /></RequireAuth>} />
      {/* Alerte → détection → document source, sur un seul écran. */}
      <Route path="/alerts/:id/chaine" element={<RequireAuth><InvestigationAlerte /></RequireAuth>} />
      <Route path="/sources" element={<RequireAuth><Sources /></RequireAuth>} />
      <Route path="/documents" element={<RequireAuth><Documents /></RequireAuth>} />
      <Route path="/detections" element={<RequireAuth><Detections /></RequireAuth>} />
      <Route path="/collecte" element={<RequireAuth><Collecte /></RequireAuth>} />
      <Route path="/planification" element={<RequireAuth><Planification /></RequireAuth>} />
      <Route path="/recherche" element={<RequireAuth><Recherche /></RequireAuth>} />
      <Route path="/comptes" element={<RequireAuth><Comptes /></RequireAuth>} />
      <Route path="/settings" element={<RequireAuth><Settings /></RequireAuth>} />
      <Route path="/telegram" element={<RequireAuth><TelegramCompte /></RequireAuth>} />
      <Route path="/watchlist" element={<RequireAuth><Watchlist /></RequireAuth>} />
      <Route path="/entities" element={<RequireAuth><Entities /></RequireAuth>} />
      <Route path="/statistics" element={<RequireAuth><Statistics /></RequireAuth>} />
      <Route path="/gouvernance" element={<RequireAuth><Gouvernance /></RequireAuth>} />
      <Route path="/perimetre" element={<RequireAuth><Perimetre /></RequireAuth>} />
      <Route
        path="/cartographie"
        element={
          <RequireAuth>
            <Suspense fallback={<p className="p-6 text-body-sm">Chargement de la carte…</p>}>
              <Cartographie />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route path="/fiabilite" element={<RequireAuth><Fiabilite /></RequireAuth>} />
      <Route path="/lookup" element={<RequireAuth><Lookup /></RequireAuth>} />
      {/* ⚠️ Route attrape-tout. Sans elle, une URL inconnue rendait un écran
          blanc : ni message, ni moyen de revenir. */}
      <Route path="*" element={<RequireAuth><NotFound /></RequireAuth>} />
    </Routes>
  );
}
