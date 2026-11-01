<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import AssistantInput from '@/components/assistant/AssistantInput.vue';
import AssistantMessages from '@/components/assistant/AssistantMessages.vue';
import AssistantOrb from '@/components/assistant/AssistantOrb.vue';
import Icon from '@/components/ui/Icon.vue';
import {
  ASSISTANT_NAME,
  assistantLookAt,
  notePointer,
  useAssistant,
} from '@/composables/useAssistant';
import { useMe } from '@/composables/useMe';
import { useViewMode } from '@/composables/useViewMode';
import {
  bubbleLine,
  BUBBLE_SHOWS_MS,
  mayShowBubble,
  pageName,
  startingSuggestions,
} from '@/lib/assistant-chat';
import {
  clampToViewport,
  isDrag,
  panelSize,
  placePanel,
  snapToEdge,
  type Insets,
  type Point,
} from '@/lib/assistant-geometry';
import { AUTH_ENABLED } from '@/lib/config';
import { DEMO_PERSON_ID } from '@/lib/labels';
import { TAB_KEY } from '@/components/senior/senior-view.js';

/**
 * Kaki on every screen: a small orb with eyes that can be dragged anywhere and settles against
 * the nearer side; a tap opens the chat, which grows out of it, next to it and inward from the
 * edge; minimising shrinks it back, keeping the conversation. Arrow keys move it; Escape closes
 * the chat. It glances at whatever is clicked (only where, never what), and now and then says
 * "Need help?". Its place is remembered in this browser.
 */
const assistant = useAssistant();
const route = useRoute();
const { mode } = useViewMode();
const { me, currentGroup } = useMe();

const senior = computed(() => mode.value === 'senior');
const orbSize = computed(() => (senior.value ? 72 : 60));
const place = ref<Point | null>(null);
const viewport = ref({ width: 1024, height: 768 });
const dock = ref<HTMLElement | null>(null);
const orbButton = ref<HTMLButtonElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const input = ref<InstanceType<typeof AssistantInput> | null>(null);
const messagesView = ref<InstanceType<typeof AssistantMessages> | null>(null);
const showPanel = ref(false);
const hovered = ref(false);
const dragging = ref(false);
const bubble = ref<string | null>(null);

const PLACE_KEY = 'careplus.assistant.place.v1';
const MARGIN = 12;

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

/** Room kept clear at the bottom of a phone for the tab bar. */
const insets = computed<Insets>(() => ({
  top: 0,
  right: 0,
  left: 0,
  bottom: viewport.value.width < 768 ? (senior.value ? 108 : 78) : 0,
}));

function defaultPlace(): Point {
  const size = orbSize.value;
  return {
    x: viewport.value.width - size - 20,
    y: viewport.value.height - size - 20 - insets.value.bottom,
  };
}

const at = computed<Point>(() =>
  clampToViewport(
    place.value ?? defaultPlace(),
    { width: orbSize.value, height: orbSize.value },
    viewport.value,
    MARGIN,
    insets.value,
  ),
);

const panelBox = computed(() => {
  const size = panelSize(viewport.value, MARGIN);
  const spot = placePanel(
    { ...at.value, width: orbSize.value, height: orbSize.value },
    size,
    viewport.value,
    MARGIN,
  );
  return { ...size, ...spot };
});

const onRight = computed(() => at.value.x + orbSize.value / 2 > viewport.value.width / 2);

// ---- Who is asking, about whom, on which page (read fresh for each question) ----

function seniorTab(): string | null {
  try {
    return window.localStorage.getItem(TAB_KEY);
  } catch {
    return null;
  }
}
assistant.setContext(() => ({
  viewer: senior.value ? 'senior' : 'family',
  personId: senior.value
    ? (me.value?.person_id ?? DEMO_PERSON_ID)
    : // Family not in a group yet: no senior to ask about, but Care+ questions still work.
      (currentGroup.value?.person_id ?? (AUTH_ENABLED ? null : DEMO_PERSON_ID)),
  page: pageName(route.path, route.path.startsWith('/senior') ? seniorTab() : null),
}));

const greeting = computed(() => {
  const name = senior.value ? me.value?.display_name : null;
  return name ? `Hello, ${name}! I'm ${ASSISTANT_NAME}.` : `Hello! I'm ${ASSISTANT_NAME}.`;
});
const starters = computed(() =>
  startingSuggestions(assistant.context().viewer, assistant.context().page),
);

// ---- Opening and closing: the chat grows out of the orb, and shrinks back into it ----

function grow(opening: boolean): Promise<void> {
  const el = panel.value;
  if (!el || reduced()) return Promise.resolve();
  const box = panelBox.value;
  const cx = at.value.x + orbSize.value / 2 - box.x;
  const cy = at.value.y + orbSize.value / 2 - box.y;
  const small = `circle(${orbSize.value / 2}px at ${cx}px ${cy}px)`;
  const big = `circle(${Math.hypot(box.width, box.height) * 1.05}px at ${cx}px ${cy}px)`;
  const frames = opening
    ? [
        { clipPath: small, opacity: 0.4 },
        { clipPath: big, opacity: 1 },
      ]
    : [
        { clipPath: big, opacity: 1 },
        { clipPath: small, opacity: 0.2 },
      ];
  return el
    .animate(frames, {
      duration: opening ? 460 : 340,
      easing: opening ? 'cubic-bezier(0.2, 0.8, 0.2, 1)' : 'cubic-bezier(0.4, 0, 0.2, 1)',
    })
    .finished.then(() => undefined)
    .catch(() => undefined);
}

async function openChat() {
  if (showPanel.value) return;
  bubble.value = null;
  assistant.setOpen(true);
  showPanel.value = true;
  await nextTick();
  if (assistant.messages.value.length) messagesView.value?.toBottom();
  input.value?.focus();
  await grow(true);
}

async function minimise() {
  if (!showPanel.value) return;
  await grow(false);
  showPanel.value = false;
  assistant.setOpen(false);
  assistant.setMood('idle');
  await nextTick();
  orbButton.value?.focus();
}

function ask(text: string) {
  void assistant.send(text);
}

// ---- Dragging the orb (a press that moves is a drag; one that does not is a tap) ----

let press: { id: number; start: Point; from: Point; moved: boolean } | null = null;
let dragged = false;

function down(event: PointerEvent) {
  if (event.button !== 0) return;
  press = {
    id: event.pointerId,
    start: { x: event.clientX, y: event.clientY },
    from: { ...at.value },
    moved: false,
  };
  // Held from the start, so a quick drag that leaves the orb at once still moves it.
  orbButton.value?.setPointerCapture?.(event.pointerId);
}

function move(event: PointerEvent) {
  if (!press || event.pointerId !== press.id) return;
  const moved = { x: event.clientX - press.start.x, y: event.clientY - press.start.y };
  if (!press.moved) {
    if (!isDrag(moved)) return;
    press.moved = true;
    dragging.value = true;
  }
  place.value = { x: press.from.x + moved.x, y: press.from.y + moved.y };
}

function up(event: PointerEvent) {
  if (!press || event.pointerId !== press.id) return;
  const wasDrag = press.moved;
  press = null;
  dragging.value = false;
  if (!wasDrag) return;
  // Only a drag that ends with a release is followed by a click to ignore.
  dragged = event.type === 'pointerup';
  place.value = snapToEdge(
    at.value,
    { width: orbSize.value, height: orbSize.value },
    viewport.value,
    MARGIN,
  );
  remember();
}

function tap() {
  if (dragged) {
    dragged = false;
    return;
  }
  void openChat();
}

/** The keyboard does what the drag does: arrows move it (Shift for bigger steps). */
function keys(event: KeyboardEvent) {
  const step = event.shiftKey ? 96 : 24;
  const moves: Record<string, Point> = {
    ArrowLeft: { x: -step, y: 0 },
    ArrowRight: { x: step, y: 0 },
    ArrowUp: { x: 0, y: -step },
    ArrowDown: { x: 0, y: step },
  };
  const by = moves[event.key];
  if (!by) return;
  event.preventDefault();
  place.value = { x: at.value.x + by.x, y: at.value.y + by.y };
  remember();
}

function remember() {
  try {
    window.localStorage.setItem(PLACE_KEY, JSON.stringify(at.value));
  } catch {
    // Storage blocked: it stays put until the page reloads.
  }
}

function recall() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(PLACE_KEY) ?? 'null') as Point | null;
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) place.value = saved;
  } catch {
    // Nothing remembered.
  }
}

// ---- Looking around: the pointer, and a glance at whatever is clicked elsewhere ----

let pending = false;
function pointerMoved(event: PointerEvent) {
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => {
    pending = false;
    notePointer(event.clientX, event.clientY);
  });
}
function clicked(event: PointerEvent) {
  if (dock.value?.contains(event.target as Node)) return;
  assistantLookAt(event.clientX, event.clientY, 800);
}

/** The visible screen: on a phone this shrinks while the keyboard is up, so the chat stays above it. */
function measure() {
  const visible = window.visualViewport;
  viewport.value = {
    width: window.innerWidth,
    height: Math.round(visible?.height ?? window.innerHeight),
  };
}

function clearChat() {
  assistant.clear();
  // The Clear button has just gone: keep focus in the chat.
  void nextTick(() => input.value?.focus());
}

// A different person, or a different senior: start a fresh conversation.
watch(
  () => [me.value?.person_id, currentGroup.value?.person_id, mode.value] as const,
  (now, before) => {
    // Only a real change of person: not their details arriving after a reload.
    const changed = before?.some((part, i) => part != null && part !== now[i]);
    if (changed) {
      assistant.reset();
      showPanel.value = false;
    }
  },
);

function escape(event: KeyboardEvent) {
  if (event.key === 'Escape' && showPanel.value) {
    event.stopPropagation();
    void minimise();
  }
}

// ---- Now and then: "Need help?" ----

let pageSince = Date.now();
let lastShown: number | null = null;
let shownCount = 0;
let bubbleTimer = 0;
let hideTimer = 0;
watch(
  () => route.path,
  () => {
    pageSince = Date.now();
    bubble.value = null;
  },
);
function maybeBubble() {
  const now = Date.now();
  if (
    !reduced() &&
    mayShowBubble({
      now,
      pageSince,
      lastShown,
      open: showPanel.value,
      hasChatted: assistant.hasChatted.value,
    })
  ) {
    bubble.value = bubbleLine(shownCount++);
    lastShown = now;
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      bubble.value = null;
    }, BUBBLE_SHOWS_MS);
  }
}

onMounted(() => {
  measure();
  recall();
  window.addEventListener('resize', measure);
  window.visualViewport?.addEventListener('resize', measure);
  window.addEventListener('pointermove', pointerMoved, { passive: true });
  window.addEventListener('pointerdown', clicked, { passive: true, capture: true });
  bubbleTimer = window.setInterval(maybeBubble, 5000);
});

onBeforeUnmount(() => {
  window.removeEventListener('resize', measure);
  window.visualViewport?.removeEventListener('resize', measure);
  // Signed out, or left the demo: nothing of this conversation stays for the next person.
  assistant.reset();
  window.removeEventListener('pointermove', pointerMoved);
  window.removeEventListener('pointerdown', clicked, { capture: true });
  window.clearInterval(bubbleTimer);
  window.clearTimeout(hideTimer);
});

const orbLabel = computed(() => {
  const unread = assistant.unread.value;
  const extra = unread ? `, ${unread} new ${unread === 1 ? 'reply' : 'replies'}` : '';
  return `Open ${ASSISTANT_NAME}, your Care+ helper${extra}`;
});
</script>

<template>
  <div
    ref="dock"
    class="kaki"
    :class="{ 'is-senior': senior, 'is-open': showPanel }"
    data-testid="assistant"
    @keydown="escape"
  >
    <Transition name="kaki-bubble">
      <p
        v-if="bubble && !showPanel"
        class="kaki-bubble"
        :class="onRight ? 'is-left' : 'is-right'"
        :style="{ left: `${at.x}px`, top: `${at.y}px`, '--orb': `${orbSize}px` }"
        aria-hidden="true"
        data-testid="assistant-bubble"
      >
        {{ bubble }}
      </p>
    </Transition>

    <button
      v-show="!showPanel"
      ref="orbButton"
      type="button"
      class="kaki-orb"
      :class="{ 'is-dragging': dragging }"
      :style="{
        transform: `translate(${at.x}px, ${at.y}px)`,
        width: `${orbSize}px`,
        height: `${orbSize}px`,
      }"
      :aria-label="orbLabel"
      aria-describedby="kaki-move-hint"
      aria-haspopup="dialog"
      :aria-expanded="showPanel"
      data-testid="assistant-orb"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
      @pointerenter="hovered = true"
      @pointerleave="hovered = false"
      @click="tap"
      @keydown="keys"
    >
      <AssistantOrb :size="orbSize" :mood="assistant.mood.value" :lifted="hovered || dragging" />
      <span
        v-if="assistant.unread.value"
        class="kaki-unread"
        aria-hidden="true"
        data-testid="assistant-unread"
      >
        {{ assistant.unread.value }}
      </span>
    </button>
    <span id="kaki-move-hint" class="visually-hidden">Arrow keys move it around the screen.</span>

    <section
      v-if="showPanel"
      ref="panel"
      class="kaki-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby="kaki-title"
      data-testid="assistant-panel"
      :style="{
        left: `${panelBox.x}px`,
        top: `${panelBox.y}px`,
        width: `${panelBox.width}px`,
        height: `${panelBox.height}px`,
      }"
    >
      <header class="kaki-head">
        <AssistantOrb :size="40" :mood="assistant.mood.value" />
        <div class="kaki-who">
          <h2 id="kaki-title" class="kaki-name">{{ ASSISTANT_NAME }}</h2>
          <p class="kaki-status">
            <span class="kaki-dot" aria-hidden="true"></span>
            {{ assistant.busy.value ? 'Thinking…' : 'Your Care+ helper' }}
          </p>
        </div>
        <button
          v-if="assistant.messages.value.length"
          type="button"
          class="kaki-icon"
          aria-label="Clear the conversation"
          title="Clear the conversation"
          data-testid="assistant-clear"
          @click="clearChat"
        >
          <Icon name="trash" />
        </button>
        <button
          type="button"
          class="kaki-icon"
          aria-label="Minimise"
          title="Minimise"
          data-testid="assistant-minimise"
          @click="minimise"
        >
          <Icon name="chevron-down" />
        </button>
      </header>

      <AssistantMessages
        ref="messagesView"
        :messages="assistant.messages.value"
        :busy="assistant.busy.value"
        :greeting="greeting"
        :starters="starters"
        @ask="ask"
      />

      <AssistantInput ref="input" :busy="assistant.busy.value" @send="ask" />
      <p class="kaki-foot">
        {{ ASSISTANT_NAME }} can make mistakes, and is not for emergencies: call 995.
      </p>
    </section>
  </div>
</template>

<style scoped>
.kaki {
  --as-ink: #102a26;
  --as-soft: #5a6f6a;
  --as-line: rgb(16 42 38 / 12%);
  --as-panel: rgb(255 255 255 / 86%);
  --as-field: rgb(255 255 255 / 92%);
  --as-bubble: rgb(16 42 38 / 6%);
  --as-hover: rgb(11 104 79 / 8%);
  --as-accent: #0b684f;
  --as-on-accent: #fff;
  --as-ring: rgb(11 104 79 / 22%);
  --as-warn: #8e2c1c;
  --as-warn-soft: #fbe3dc;
  font-size: 1rem;
}
:root[data-bs-theme='dark'] .kaki {
  --as-ink: #e3ece8;
  --as-soft: #a7b8b2;
  --as-line: rgb(255 255 255 / 12%);
  --as-panel: rgb(20 30 28 / 88%);
  --as-field: rgb(255 255 255 / 6%);
  --as-bubble: rgb(255 255 255 / 8%);
  --as-hover: rgb(95 211 176 / 12%);
  --as-accent: #5fd3b0;
  --as-on-accent: #0b2a22;
  --as-ring: rgb(95 211 176 / 28%);
  --as-warn: #ffb4a6;
  --as-warn-soft: rgb(178 58 38 / 25%);
}
.kaki.is-senior {
  font-size: 1.15rem;
}

/* The orb: fixed to the screen, moved with a transform so dragging stays smooth. */
.kaki-orb {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 1045;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: grab;
  touch-action: none;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}
.kaki-orb.is-dragging {
  cursor: grabbing;
}
.kaki-orb:not(.is-dragging) {
  transition: transform 0.35s var(--sl-ease-spring);
}
.kaki-orb:focus-visible {
  outline: 3px solid var(--sl-blue-deep);
  outline-offset: 4px;
}
.kaki-unread {
  position: absolute;
  top: -2px;
  right: -2px;
  display: grid;
  place-items: center;
  min-width: 1.4rem;
  height: 1.4rem;
  padding: 0 0.35rem;
  border: 2px solid var(--sl-surface);
  border-radius: 999px;
  background: #d93a4a;
  color: #fff;
  font-size: 0.75rem;
  font-weight: 800;
}

/* "Need help?": a small speech bubble beside the orb, on the side with room. */
.kaki-bubble {
  position: fixed;
  z-index: 1044;
  margin: 0;
  padding: 0.5rem 0.85rem;
  border: 1px solid var(--as-line);
  border-radius: 1rem;
  background: var(--as-panel);
  backdrop-filter: blur(14px) saturate(1.5);
  -webkit-backdrop-filter: blur(14px) saturate(1.5);
  box-shadow: 0 8px 24px rgb(16 42 38 / 16%);
  color: var(--as-ink);
  font-weight: 700;
  white-space: nowrap;
  pointer-events: none;
}
.kaki-bubble.is-left {
  transform: translate(calc(-100% - 10px), calc(var(--orb) * 0.18));
  border-bottom-right-radius: 0.3rem;
}
.kaki-bubble.is-right {
  transform: translate(calc(var(--orb) + 10px), calc(var(--orb) * 0.18));
  border-bottom-left-radius: 0.3rem;
}
.kaki-bubble-enter-active,
.kaki-bubble-leave-active {
  transition:
    opacity 0.3s ease,
    scale 0.3s var(--sl-ease-spring);
}
.kaki-bubble-enter-from,
.kaki-bubble-leave-to {
  opacity: 0;
  scale: 0.85;
}

/* The chat: frosted glass, next to the orb. */
.kaki-panel {
  position: fixed;
  z-index: 1046;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--as-line);
  border-radius: 1.5rem;
  background: var(--as-panel);
  backdrop-filter: blur(22px) saturate(1.6);
  -webkit-backdrop-filter: blur(22px) saturate(1.6);
  box-shadow:
    0 24px 60px rgb(16 42 38 / 22%),
    0 4px 14px rgb(16 42 38 / 10%);
  color: var(--as-ink);
}
.kaki-head {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.75rem 0.6rem 0.75rem 0.9rem;
  border-bottom: 1px solid var(--as-line);
}
.kaki-who {
  flex: 1;
  min-width: 0;
}
.kaki-name {
  margin: 0;
  font-size: 1.05em;
  font-weight: 800;
  color: var(--as-ink);
}
.kaki-status {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0;
  color: var(--as-soft);
  font-size: 0.8em;
}
.kaki-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: #2fbf71;
  box-shadow: 0 0 0 3px rgb(47 191 113 / 20%);
}
.kaki-icon {
  display: inline-grid;
  place-items: center;
  width: 2.75rem;
  height: 2.75rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--as-soft);
}
.kaki-icon:hover {
  background: var(--as-hover);
  color: var(--as-ink);
}
.kaki-icon:focus-visible {
  outline: 3px solid var(--as-accent);
  outline-offset: 1px;
}
.kaki-foot {
  margin: 0;
  padding: 0 0.9rem 0.6rem;
  color: var(--as-soft);
  font-size: 0.72em;
  text-align: center;
}
@media (prefers-reduced-motion: reduce) {
  .kaki-orb:not(.is-dragging) {
    transition: none;
  }
}
</style>
