import { useEffect, useRef } from "react";

type DynamicWeightTextProps = {
  label: string;
  className?: string;
  fromWeight?: number;
  toWeight?: number;
  reach?: number;
};

/** Animate only the supplied brand word, using the app's existing typeface. */
export function DynamicWeightText({
  label,
  className,
  fromWeight = 300,
  toWeight = 800,
  reach = 140,
}: DynamicWeightTextProps) {
  const containerRef = useRef<HTMLSpanElement>(null);
  const letterRefs = useRef<Array<HTMLSpanElement | null>>([]);
  const pointer = useRef({ x: -10000, y: -10000 });
  const frame = useRef(0);

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      pointer.current = { x: event.clientX, y: event.clientY };
      if (!frame.current) frame.current = requestAnimationFrame(updateWeights);
    };

    function updateWeights() {
      frame.current = 0;
      const { x, y } = pointer.current;
      letterRefs.current.forEach((letter) => {
        if (!letter) return;
        const bounds = letter.getBoundingClientRect();
        const distance = Math.hypot(
          x - (bounds.left + bounds.width / 2),
          y - (bounds.top + bounds.height / 2),
        );
        const proximity = Math.max(0, 1 - distance / reach);
        letter.style.fontWeight = String(Math.round(fromWeight + (toWeight - fromWeight) * proximity));
      });
    }

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [fromWeight, reach, toWeight]);

  letterRefs.current = [];
  return (
    <span ref={containerRef} className={className} aria-label={label}>
      {Array.from(label).map((letter, index) => (
        <span
          aria-hidden="true"
          key={`${letter}-${index}`}
          ref={(node) => { letterRefs.current[index] = node; }}
          style={{ display: "inline-block", fontWeight: fromWeight, transition: "font-weight 120ms ease-out" }}
        >
          {letter === " " ? "\u00a0" : letter}
        </span>
      ))}
    </span>
  );
}

export default DynamicWeightText;
