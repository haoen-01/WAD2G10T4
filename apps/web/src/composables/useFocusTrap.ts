import { onBeforeUnmount, type Ref } from 'vue';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** The things Tab can reach inside `container`, in order, leaving out anything hidden. */
function tabbables(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) =>
      element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden',
  );
}

/**
 * Keeps Tab and Shift+Tab inside one element (a dialog) while it is active, and pulls focus back if
 * it somehow lands outside. Hand-written because it is small and the app takes no focus-trap package.
 * `activate` and `deactivate` are safe to call twice; unmounting deactivates.
 */
export function useFocusTrap(container: Ref<HTMLElement | null>) {
  let active = false;
  let lastInside: HTMLElement | null = null;
  let observer: MutationObserver | null = null;

  /** Toast buttons (Undo) live outside the dialog; they close the Tab cycle after its own items. */
  function toastTabbables(): HTMLElement[] {
    const host = document.querySelector<HTMLElement>('.sl-toasts');
    return host ? tabbables(host) : [];
  }

  function onKeydown(event: KeyboardEvent) {
    const root = container.value;
    if (event.key !== 'Tab' || !root) return;
    const items = [...tabbables(root), ...toastTabbables()];
    if (items.length === 0) {
      event.preventDefault();
      root.focus();
      return;
    }
    const current = document.activeElement;
    const index = items.findIndex((item) => item === current);
    const inside =
      current instanceof HTMLElement && (root.contains(current) || !!current.closest('.sl-toasts'));
    // The toast host is a separate place in the page, so the browser's own Tab order would not
    // follow `items`: step through them ourselves.
    if (index !== -1) {
      event.preventDefault();
      items[(index + (event.shiftKey ? -1 : 1) + items.length) % items.length].focus();
    } else if (!inside) {
      event.preventDefault();
      (event.shiftKey ? items[items.length - 1] : items[0]).focus();
    } else if (event.shiftKey) {
      // From the dialog or its heading (not in the Tab order): wrap round to the end.
      event.preventDefault();
      items[items.length - 1].focus();
    }
  }

  function onFocusin(event: FocusEvent) {
    const root = container.value;
    if (root && event.target instanceof HTMLElement && root.contains(event.target)) {
      lastInside = event.target;
    }
    if (!root || !(event.target instanceof Node) || root.contains(event.target)) return;
    // A toast (its Undo) lives outside the dialog on purpose and may take focus.
    if (event.target instanceof Element && event.target.closest('.sl-toasts')) return;
    (tabbables(root)[0] ?? root).focus();
  }

  // A toast that held focus was removed (Undo, dismiss, timeout): focus fell to <body>, so bring it
  // back to the last control used in the dialog, or the dialog itself.
  function restoreFocus() {
    const root = container.value;
    const now = document.activeElement;
    if (!root || (now && now !== document.body)) return;
    const back = lastInside && root.contains(lastInside) ? lastInside : null;
    (back ?? root.querySelector<HTMLElement>('[tabindex="-1"]') ?? root).focus({
      preventScroll: true,
    });
  }

  function activate() {
    if (active) return;
    active = true;
    const toasts = document.querySelector('.sl-toasts');
    if (toasts) {
      observer = new MutationObserver(restoreFocus);
      observer.observe(toasts, { childList: true, subtree: true });
    }
    document.addEventListener('keydown', onKeydown);
    document.addEventListener('focusin', onFocusin);
  }

  function deactivate() {
    if (!active) return;
    active = false;
    observer?.disconnect();
    observer = null;
    lastInside = null;
    document.removeEventListener('keydown', onKeydown);
    document.removeEventListener('focusin', onFocusin);
  }

  onBeforeUnmount(deactivate);
  return { activate, deactivate };
}
