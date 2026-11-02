import { AppLayout } from "../components/layout/AppLayout";
import { DreadSearchPanel } from "../components/watchlist/DreadSearchPanel";
import { WatchlistPanel } from "../components/watchlist/WatchlistPanel";

export function Watchlist() {
  return (
    <AppLayout title="Watchlist">
      <div className="max-w-2xl space-y-6">
        <WatchlistPanel />
        <DreadSearchPanel />
      </div>
    </AppLayout>
  );
}
