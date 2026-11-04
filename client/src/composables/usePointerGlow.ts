import { onBeforeUnmount, onMounted, type Ref } from 'vue';

import { isNear, lean, localPoint } from '@/lib/pointer-glow';

/** Everything whose edge lights up near the mouse (see "Glowing edges" in `theme.css`). */
const GLOWING = '.sl-panel, .card, .sl-glow';

/**
 * Makes the page answer the mouse, with one `pointermove` listener for the whole app (started by
 * `AppLayout.vue`):
 * - the living background (`background`) gets `--sl-mx` / `--sl-my` (where the mouse is) and
 *   `--sl-lean-x` / `--sl-lean-y` (-1 to 1), so its glow follows and its layers lean;
 * - every panel near the mouse gets `--sl-x` / `--sl-y` (the mouse inside it) and
 *   `--sl-glow-on: 1`, which lights its edge; panels it has left fade back to 0.
 *
 * Only for a mouse or trackpad (touch has no hover). At most one update per screen refresh
 * (`requestAnimationFrame`); it reads every position before writing any, so the browser lays the
 * page out once per frame, and writes a variable only when its value changes. Plain Vue and DOM,
 * so it can live in the layout.
 */
export function usePointerGlow(background: Ref<HTMLElement | null>) {
  let frame = 0;
  let x = 0;
  let y = 0;
  let inside = false;
  const lit = new Set<HTMLElement>();
  let finePointer: MediaQueryList | null = null;

  /** Sets a CSS variable only when its value changes (each change restyles the panel). */
  function put(element: HTMLElement, name: string, value: string) {
    if (element.style.getPropertyValue(name) !== value) element.style.setProperty(name, value);
  }

  function paint() {
    frame = 0;
    // Read first: every panel's place on screen.
    const panels = Array.from(document.querySelectorAll<HTMLElement>(GLOWING));
    const boxes = panels.map((panel) => panel.getBoundingClientRect());

    // Then write.
    panels.forEach((panel, index) => {
      const box = boxes[index];
      if (inside && isNear(box, x, y)) {
        const point = localPoint(box, x, y);
        put(panel, '--sl-x', `${point.x}px`);
        put(panel, '--sl-y', `${point.y}px`);
        put(panel, '--sl-glow-on', '1');
        lit.add(panel);
      } else if (lit.has(panel)) {
        put(panel, '--sl-glow-on', '0');
        lit.delete(panel);
      }
    });
    // Panels that left the page (a route change) are simply forgotten.
    for (const panel of lit) if (!panel.isConnected) lit.delete(panel);

    const layer = background.value;
    if (layer) {
      put(layer, '--sl-mx', `${Math.round(x)}px`);
      put(layer, '--sl-my', `${Math.round(y)}px`);
      put(layer, '--sl-lean-x', String(lean(x, window.innerWidth)));
      put(layer, '--sl-lean-y', String(lean(y, window.innerHeight)));
      put(layer, '--sl-follow', inside ? '1' : '0');
    }
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(paint);
  }

  /** Scrolling moves the panels under a still mouse; with the mouse away there is nothing to do. */
  function onScroll() {
    if (inside || lit.size > 0) schedule();
  }

  function onMove(event: PointerEvent) {
    if (event.pointerType === 'touch') return;
    x = event.clientX;
    y = event.clientY;
    inside = true;
    schedule();
  }

  function onOut(event: PointerEvent) {
    // `relatedTarget` is null when the mouse leaves the window itself.
    if (event.relatedTarget) return;
    inside = false;
    schedule();
  }

  function start() {
    window.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('pointerout', onOut, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  function stop() {
    window.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerout', onOut);
    window.removeEventListener('scroll', onScroll);
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    // Put everything out, in case the mouse went away (a trackpad unplugged, say).
    for (const panel of lit) panel.style.setProperty('--sl-glow-on', '0');
    lit.clear();
    inside = false;
    background.value?.style.setProperty('--sl-follow', '0');
  }

  function onPointerKind() {
    stop();
    if (finePointer?.matches) start();
  }

  onMounted(() => {
    finePointer = window.matchMedia('(pointer: fine)');
    finePointer.addEventListener('change', onPointerKind);
    onPointerKind();
  });

  onBeforeUnmount(() => {
    finePointer?.removeEventListener('change', onPointerKind);
    stop();
  });
}
