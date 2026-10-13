/** Seconds a copied secret stays on the clipboard. */
export const CLIPBOARD_CLEAR_SECONDS = 30;

let pendingClear: ReturnType<typeof setTimeout> | null = null;

/**
 * Copy a secret, then clear the clipboard after `CLIPBOARD_CLEAR_SECONDS`.
 *
 * A password left on the clipboard is pasted into the next chat message, the
 * next search box, or read by the next app that asks — the vault's own copy
 * buttons are how most of them get there. The clear is unconditional (reading
 * the clipboard back to check it first would prompt for permission every
 * time), and a newer copy restarts the timer so it never cuts one short.
 * Writing fails silently when the tab is not focused; nothing to do then.
 */
export async function copySecret(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    return false;
  }
  if (pendingClear) clearTimeout(pendingClear);
  pendingClear = setTimeout(() => {
    pendingClear = null;
    navigator.clipboard.writeText("").catch(() => {});
  }, CLIPBOARD_CLEAR_SECONDS * 1000);
  return true;
}
