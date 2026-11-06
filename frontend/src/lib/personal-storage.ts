/** Browser copies of one person's work (Casper chats, typed quick picks). Dropped on sign-out and when the
 * session expires, so the next person to sign in on this browser never sees them. */
const PREFIXES = ["aa:assistant:messages", "aa:quick:"];

export function clearPersonalStorage(): void {
  for (const store of [sessionStorage, localStorage]) {
    try {
      for (let i = store.length - 1; i >= 0; i--) {
        const key = store.key(i);
        if (key && PREFIXES.some((p) => key.startsWith(p))) store.removeItem(key);
      }
    } catch {
      // storage blocked: nothing was kept either
    }
  }
}
