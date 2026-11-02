interface SparklineProps {
  points: number[];
  colorClassName?: string;
}

/** Mini sparkline SVG — points normalisés en interne sur une hauteur de 25.
 * La ligne se dessine au montage (voir .sparkline-draw dans index.css) au
 * lieu d'apparaitre figee ; le dernier point est marque pour ancrer l'oeil
 * sur la valeur la plus recente. */
export function Sparkline({ points, colorClassName = "stroke-signal" }: SparklineProps) {
  const max = Math.max(...points, 1);
  const coords = points.map((p, i) => [(i / (points.length - 1)) * 100, 25 - (p / max) * 25] as const);
  const pathD = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
  const [lastX, lastY] = coords[coords.length - 1] ?? [0, 0];
  // Longueur approximative du tracé, assez large pour couvrir n'importe quelle forme de courbe.
  const pathLength = 260;

  return (
    <svg className={`h-6 w-24 fill-none ${colorClassName}`} viewBox="0 0 100 25" overflow="visible">
      <path
        d={pathD}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="sparkline-draw"
        style={{ strokeDasharray: pathLength, strokeDashoffset: pathLength }}
      />
      <circle cx={lastX} cy={lastY} r="2.2" className="fill-current stroke-none" />
    </svg>
  );
}
