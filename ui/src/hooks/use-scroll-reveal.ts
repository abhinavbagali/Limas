import { useEffect, type RefObject } from "react";

export function useScrollReveal(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const elements = root.current?.querySelectorAll<HTMLElement>(".scroll-reveal");
    if (!elements?.length) return;
    if (!("IntersectionObserver" in window)) {
      elements.forEach((element) => element.classList.add("is-revealed"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-revealed");
            observer.unobserve(entry.target);
          }
        }),
      { threshold: 0.08, rootMargin: "0px 0px -30px 0px" },
    );
    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [root]);
}
