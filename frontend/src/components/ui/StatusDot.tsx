interface StatusDotProps {
  color: "ok" | "warn" | "critical" | "info" | "signal" | "dim";
  pulse?: boolean;
}

const colorClasses: Record<StatusDotProps["color"], string> = {
  ok: "bg-ok shadow-[0_0_8px_-1px_theme(colors.ok)]",
  warn: "bg-warn shadow-[0_0_8px_-1px_theme(colors.warn)]",
  critical: "bg-critical shadow-[0_0_8px_-1px_theme(colors.critical)]",
  info: "bg-info shadow-[0_0_8px_-1px_theme(colors.info)]",
  signal: "bg-signal shadow-[0_0_8px_-1px_theme(colors.signal)]",
  dim: "bg-ink-faint",
};

export function StatusDot({ color, pulse = false }: StatusDotProps) {
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${colorClasses[color]} ${pulse ? "status-pulse" : ""}`} />;
}
