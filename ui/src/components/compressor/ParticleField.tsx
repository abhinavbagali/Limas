import { useEffect, useRef } from "react";

export function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let width = 0;
    let height = 0;

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      width = bounds.width;
      height = bounds.height;
      canvas.width = Math.max(1, Math.floor(width * pixelRatio));
      canvas.height = Math.max(1, Math.floor(height * pixelRatio));
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      paint();
    };
    const paint = () => {
      if (!context) return;
      context.clearRect(0, 0, width, height);
      const style = getComputedStyle(document.documentElement);
      const particleColor = style.getPropertyValue("--particle").trim() || "oklch(.5 0 0 / .2)";
      for (let index = 0; index < 65; index += 1) {
        const x = ((index * 173.7) % 997) / 997 * width;
        const y =
          (((index * 89.3) % 991) / 991 * height) +
          (reducedMotion ? 0 : Math.sin(frame / 130 + index) * 5);
        context.beginPath();
        context.fillStyle = particleColor;
        context.arc(x, y, index % 4 === 0 ? 1.6 : 1, 0, Math.PI * 2);
        context.fill();
      }
      frame += 1;
      if (!reducedMotion) requestAnimationFrame(paint);
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  return <canvas ref={canvasRef} className="particle-field" aria-hidden="true" />;
}
