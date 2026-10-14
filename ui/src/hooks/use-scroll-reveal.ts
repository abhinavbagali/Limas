import { useEffect, type DependencyList, type RefObject } from "react";

export function useScrollReveal(
  root: RefObject<HTMLElement | null>,
  deps: DependencyList = [],
) {
  useEffect(() => {
    if (!root.current) return;
    if (!("IntersectionObserver" in window)) {
      const elements = root.current.querySelectorAll<HTMLElement>(".scroll-reveal");
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
      { threshold: 0.05, rootMargin: "0px 0px -40px 0px" },
    );

    const observeAll = () => {
      const elements = root.current?.querySelectorAll<HTMLElement>(".scroll-reveal:not(.is-revealed)");
      elements?.forEach((element) => {
        // If element is already within viewport on mount, reveal immediately
        const rect = element.getBoundingClientRect();
        if (rect.top < window.innerHeight && rect.bottom > 0) {
          element.classList.add("is-revealed");
        } else {
          observer.observe(element);
        }
      });
    };

    observeAll();

    // In case new children are rendered dynamically (e.g. charts / async data)
    const mutationObserver = new MutationObserver(() => {
      observeAll();
    });

    mutationObserver.observe(root.current, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      mutationObserver.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root, ...deps]);
}
