import { AppLayout } from "../components/layout/AppLayout";
import { EntitiesPanel } from "../components/entities/EntitiesPanel";

export function Entities() {
  return (
    <AppLayout title="Organisations surveillées">
      <EntitiesPanel />
    </AppLayout>
  );
}
