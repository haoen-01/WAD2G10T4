import { reactive } from 'vue';

/**
 * Short confirmations that float at the bottom of the screen ("Copied", "Removed. Undo"). Shared by
 * every screen (a module singleton) and rendered once by `ToastHost.vue` inside a polite live
 * region, so a screen-reader user hears them too.
 *
 * A toast never replaces the message a form already shows next to itself; it is for actions that
 * have nowhere else to confirm, and for offering an undo.
 */
export interface Toast {
  id: number;
  message: string;
  actionLabel?: string;
  action?: () => void;
}

const MAX_SHOWN = 3;

const toasts = reactive<Toast[]>([]);
const timers = new Map<number, number>();
let nextId = 1;

export function dismissToast(id: number): void {
  const index = toasts.findIndex((toast) => toast.id === id);
  if (index !== -1) toasts.splice(index, 1);
  const timer = timers.get(id);
  if (timer !== undefined) window.clearTimeout(timer);
  timers.delete(id);
}

/** Shows a toast. One with an action (an undo) stays a little longer, so there is time to use it. */
export function showToast(
  message: string,
  options: { actionLabel?: string; action?: () => void; duration?: number } = {},
): number {
  const id = nextId++;
  toasts.push({ id, message, actionLabel: options.actionLabel, action: options.action });
  while (toasts.length > MAX_SHOWN) dismissToast(toasts[0].id);
  const duration = options.duration ?? (options.action ? 8000 : 4500);
  timers.set(
    id,
    window.setTimeout(() => dismissToast(id), duration),
  );
  return id;
}

export function useToasts() {
  return { toasts, dismiss: dismissToast };
}
