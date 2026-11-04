import { ref, watch } from 'vue';

/**
 * How the reader likes the app to look, shared by the whole app and kept in this browser.
 *
 * - Zoom, as a percentage (80% to 150%). It sets the root font size; Bootstrap sizes everything in
 *   rem, so every screen grows with it. Older eyes are the reason this exists.
 * - Light or dark. It sets `data-bs-theme` on <html>, which both Bootstrap and `theme.css` follow.
 *   With nothing chosen yet, it follows the device's own setting.
 *
 * Care+'s green cursors are not a setting: they are always on with a mouse or trackpad (see
 * "Cursors" in `theme.css`).
 */
export type Theme = 'light' | 'dark';

export const ZOOM_STEPS = [80, 90, 100, 110, 125, 150] as const;
const ZOOM_KEY = 'careplus.zoom.v1';
const THEME_KEY = 'careplus.theme.v1';
/** The text size buttons this replaced, so a size chosen before carries over. */
const OLD_TEXT_SIZE_KEY = 'silverloop.textSize.v1';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readZoom(): number {
  try {
    const saved = Number(storage()?.getItem(ZOOM_KEY));
    if ((ZOOM_STEPS as readonly number[]).includes(saved)) return saved;
    const old = storage()?.getItem(OLD_TEXT_SIZE_KEY);
    if (old === 'large') return 110;
    if (old === 'largest') return 125;
  } catch {
    // Storage blocked: start at 100%.
  }
  return 100;
}

function readTheme(): Theme {
  try {
    const saved = storage()?.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // Storage blocked: follow the device.
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function save(key: string, value: string) {
  try {
    storage()?.setItem(key, value);
  } catch {
    // Private browsing: the choice still applies until the page is closed.
  }
}

const zoom = ref(readZoom());
const theme = ref<Theme>(readTheme());

function applyZoom(percent: number) {
  document.documentElement.style.fontSize = percent === 100 ? '' : `${percent}%`;
}
function applyTheme(next: Theme) {
  document.documentElement.setAttribute('data-bs-theme', next);
}
applyZoom(zoom.value);
applyTheme(theme.value);

watch(zoom, (next) => {
  applyZoom(next);
  save(ZOOM_KEY, String(next));
});
watch(theme, (next) => {
  applyTheme(next);
  save(THEME_KEY, next);
});

export function useDisplay() {
  const index = () => ZOOM_STEPS.indexOf(zoom.value as (typeof ZOOM_STEPS)[number]);
  return {
    zoom,
    theme,
    zoomIn: () => {
      zoom.value = ZOOM_STEPS[Math.min(index() + 1, ZOOM_STEPS.length - 1)];
    },
    zoomOut: () => {
      zoom.value = ZOOM_STEPS[Math.max(index() - 1, 0)];
    },
    resetZoom: () => {
      zoom.value = 100;
    },
    canZoomIn: () => index() < ZOOM_STEPS.length - 1,
    canZoomOut: () => index() > 0,
    toggleTheme: () => {
      theme.value = theme.value === 'dark' ? 'light' : 'dark';
    },
  };
}
