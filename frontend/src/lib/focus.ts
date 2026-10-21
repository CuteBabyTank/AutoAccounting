// Point at something after a jump (a notification click): scroll the element marked data-focus="<name>" into view
// and ring it for about two seconds. The target page may still be loading, so this polls until it appears.

const FLASH_CLASS = "aa-focus-flash";
const FLASH_MS = 2200;
const WAIT_MS = 8000;
const POLL_MS = 150;

let poll: ReturnType<typeof setInterval> | null = null;

/** The work board listens for this (detail = a query string: tab, company) to switch view without a reload. */
export const WORK_TARGET_EVENT = "aa:work-target";

/** The value for a data-focus attribute (keeps the names in one place). */
export const focusName = {
  card: (key: string) => `card:${key}`,
  task: (id: string) => `task:${id}`,
  health: (check: "review" | "bank" | "cwt", companyId: string) => `health:${check}:${companyId}`,
  recurring: (companyId: string) => `recurring:${companyId}`,
};

function shown(el: Element): boolean {
  return el.getClientRects().length > 0;
}

/** Wait (up to 8 s) for the element named ``name`` on page ``path``, then scroll to it and flash it. Waiting for the
 *  path keeps a same-named element on the page being left from flashing. A newer call replaces this one. */
export function flashFocus(name: string, path: string): void {
  if (typeof window === "undefined") return;
  if (poll) clearInterval(poll);
  const until = Date.now() + WAIT_MS;
  const selector = `[data-focus="${CSS.escape(name)}"]`;
  const attempt = () => {
    const el = window.location.pathname === path ? document.querySelector(selector) : null;
    if (el && shown(el)) {
      if (poll) clearInterval(poll);
      poll = null;
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "center" });
      el.classList.remove(FLASH_CLASS);
      // restart the animation if the same element is flashed twice in a row
      void (el as HTMLElement).offsetWidth;
      el.classList.add(FLASH_CLASS);
      setTimeout(() => el.classList.remove(FLASH_CLASS), FLASH_MS);
    } else if (Date.now() > until) {
      if (poll) clearInterval(poll);
      poll = null;
    }
  };
  poll = setInterval(attempt, POLL_MS);
}
