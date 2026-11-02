import type { AlertSeverity } from "../../types/domain";
import { severityColors, severityLabels } from "../../lib/taxonomy";

interface SeverityBadgeProps {
  severity: AlertSeverity;
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const isCritical = severity === "critical";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-caption font-caption uppercase ${severityColors[severity]} ${
        isCritical ? "animate-pulse-critical" : ""
      }`}
    >
      {severityLabels[severity]}
    </span>
  );
}
