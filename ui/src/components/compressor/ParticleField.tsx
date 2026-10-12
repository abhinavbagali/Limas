import { useEffect, useRef } from "react";

export function ParticleField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let animationFrame = 0;
    let width = 0;
    let height = 0;
    let pointerX = -1000;
    let pointerY = -1000;
    const particles = Array.from({ length: 76 }, (_, index) => ({
      x: ((index * 173.7) % 997) / 997,
      y: ((index * 89.3) % 991) / 991,
      phase: index * 0.7,
      speed: 0.12 + (index % 5) * 0.025,
    }));

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      width = bounds.width;
      height = bounds.height;
      canvas.width = Math.max(1, Math.floor(width * pixelRatio));
      canvas.height = Math.max(1, Math.floor(height * pixelRatio));
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      draw();
    };
    const draw = () => {
      context.clearRect(0, 0, width, height);
      const style = getComputedStyle(canvas.closest(".app-shell") ?? document.documentElement);
      const particleColor = style.getPropertyValue("--particle").trim() || "oklch(.5 0 0 / .2)";
      const points = particles.map((particle) => {
        let x = particle.x * width;
        let y = particle.y * height + Math.sin(particle.phase) * 5;
        const dx = pointerX - x;
        const dy = pointerY - y;
        const distance = Math.hypot(dx, dy);
        if (!reducedMotion && distance < 145 && distance > 0) {
          const influence = (1 - distance / 145) * 18;
          x -= (dx / distance) * influence;
          y -= (dy / distance) * influence;
        }
        context.beginPath();
        context.fillStyle = particleColor;
        context.arc(x, y, particle.speed > 0.2 ? 1.8 : 1.3, 0, Math.PI * 2);
        context.fill();
        return { x, y };
      });
      context.globalAlpha = 0.22;
      context.strokeStyle = particleColor;
      for (let index = 0; index < points.length; index += 1) {
        const next = points[(index + 1) % points.length];
        if (Math.hypot(points[index].x - next.x, points[index].y - next.y) < 95) {
          context.beginPath();
          context.moveTo(points[index].x, points[index].y);
          context.lineTo(next.x, next.y);
          context.stroke();
        }
      }
      context.globalAlpha = 1;
    };
    const animate = () => {
      particles.forEach((particle) => {
        particle.phase += particle.speed * 0.008;
        if (!reducedMotion) {
          particle.x += Math.cos(particle.phase) * 0.000035;
          particle.y += Math.sin(particle.phase * 0.83) * 0.000025;
          if (particle.x < 0) particle.x = 1;
          if (particle.x > 1) particle.x = 0;
          if (particle.y < 0) particle.y = 1;
          if (particle.y > 1) particle.y = 0;
        }
      });
      draw();
      if (!reducedMotion) animationFrame = requestAnimationFrame(animate);
    };
    const trackPointer = (event: PointerEvent) => {
      const bounds = canvas.getBoundingClientRect();
      pointerX = event.clientX - bounds.left;
      pointerY = event.clientY - bounds.top;
      if (reducedMotion) draw();
    };
    resize();
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", trackPointer, { passive: true });
    if (!reducedMotion) animationFrame = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(animationFrame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", trackPointer);
    };
  }, []);

  return <canvas ref={canvasRef} className="particle-field" aria-hidden="true" />;
}
