import { useEffect, useRef, useState } from "react";

interface AnimatedNumberProps {
  value: number;
  durationMs?: number;
}

/** Compte de 0 jusqu'à `value` au montage — un chiffre qui apparaît figé ne
 * dit rien, un chiffre qui "arrive" attire l'oeil sur ce qui vient d'être
 * mesuré. Respecte prefers-reduced-motion (saute directement à la valeur). */
export function AnimatedNumber({ value, durationMs = 900 }: AnimatedNumberProps) {
  const [display, setDisplay] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      setDisplay(value);
      return;
    }

    // Reinitialise l'origine temporelle a chaque nouvelle valeur : sans cela
    // startRef garde le timestamp du premier montage, `elapsed` depasse
    // immediatement durationMs et toute mise a jour ulterieure de `value`
    // s'affiche d'un coup au lieu d'etre animee.
    startRef.current = null;

    let frame = requestAnimationFrame(function step(timestamp: number) {
      if (startRef.current === null) startRef.current = timestamp;
      const elapsed = timestamp - startRef.current;
      const progress = Math.min(elapsed / durationMs, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(eased * value));
      if (progress < 1) frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [value, durationMs]);

  return <>{display.toLocaleString("fr-FR")}</>;
}
