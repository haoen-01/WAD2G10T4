<script setup lang="ts">
import type { NotificationItem } from '@silverloop/api-client';
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';

import Icon from '@/components/ui/Icon.vue';
import { answerAsk } from '@/composables/useAsks';
import { useNotifications } from '@/composables/useNotifications';
import { useNow } from '@/composables/useNow';
import {
  askOutcome,
  badgeText,
  bellLabel,
  canAnswer,
  notificationLink,
  notificationSentence,
  unreadIds,
} from '@/lib/asks';
import { relativeTime } from '@/lib/family-feed';

/**
 * The bell in the family header: the member's notifications across all their family groups, each
 * labelled with its group (the senior's name), with the unread count on the button. It is loaded
 * on its own (`defineAsyncComponent` in the layout) and uses no motion code.
 *
 * A disclosure like the Settings popover: the button opens a panel, focus moves to its heading,
 * Tab walks through it, and Escape, a click outside or Tab leaving it closes it and (for Escape)
 * returns focus to the bell; Escape works from anywhere on the page while it is open. Opening marks
 * the notifications it shows read; the ones that were unread keep a "New" mark until it closes. An
 * ask still open for you carries "Yes, I'll go" and "Can't go"; once answered (or ended) the item
 * says how, and focus stays on it. A notification about a day that still exists links to it on the
 * calendar.
 */
const bell = useNotifications();
const now = useNow();
const route = useRoute();

const open = ref(false);
const root = ref<HTMLElement | null>(null);
const button = ref<HTMLButtonElement | null>(null);
const heading = ref<HTMLElement | null>(null);
const panelId = `bell-${useId()}`;
/** What was unread when the panel opened, so it can still say "New" while open. */
const fresh = ref<ReadonlySet<string>>(new Set());
const answering = ref<string | null>(null);

const label = computed(() => bellLabel(bell.unread.value));
const badge = computed(() => badgeText(bell.unread.value));

function markShownRead() {
  const ids = unreadIds(bell.items.value);
  fresh.value = new Set([...fresh.value, ...ids]);
  void bell.markRead(ids);
}

async function show() {
  open.value = true;
  fresh.value = new Set();
  await nextTick();
  heading.value?.focus();
  markShownRead();
  // Then read again, and mark anything newer that arrived as shown too.
  await bell.refresh();
  if (open.value) markShownRead();
}

function close(returnFocus = false) {
  open.value = false;
  fresh.value = new Set();
  if (returnFocus) void nextTick(() => button.value?.focus());
}

function toggle() {
  if (open.value) close();
  else void show();
}

/** Every notification shown here, read: never ones further back that have not been seen. */
function markAll() {
  fresh.value = new Set();
  void bell.markRead(unreadIds(bell.items.value));
}

const itemEls = new Map<string, HTMLElement>();
function itemRef(id: string) {
  return (element: unknown) => {
    if (element instanceof HTMLElement) itemEls.set(id, element);
    else itemEls.delete(id);
  };
}

async function answer(item: NotificationItem, yes: boolean) {
  if (answering.value) return;
  answering.value = item.notification_id;
  try {
    await answerAsk(item.group_id, item.ask_id, yes, {
      title: item.appointment_title,
      askerName: item.asker_name,
    });
    await bell.refresh();
  } finally {
    answering.value = null;
  }
  // The buttons have gone and the item now says how it ended: keep focus on it, inside the panel.
  await nextTick();
  if (open.value) (itemEls.get(item.notification_id) ?? heading.value)?.focus();
}

/** Following a notification's link always lands on it, even from the calendar it points to. */
function follow() {
  close();
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.stopPropagation();
    close(true);
  }
}

// While open, Escape works wherever focus is (it can end up on the page after a re-render).
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !open.value) return;
  if (root.value?.contains(event.target as Node)) return; // handled by `onKeydown`
  close(true);
}

function onFocusout(event: FocusEvent) {
  const next = event.relatedTarget as Node | null;
  if (open.value && next && !root.value?.contains(next)) close();
}

function onPointerdown(event: PointerEvent) {
  if (open.value && !root.value?.contains(event.target as Node)) close();
}

watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onPointerdown);
    document.addEventListener('keydown', onDocumentKeydown);
  } else {
    document.removeEventListener('pointerdown', onPointerdown);
    document.removeEventListener('keydown', onDocumentKeydown);
  }
});
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerdown);
  document.removeEventListener('keydown', onDocumentKeydown);
});

// A page change re-reads the bell (and closes it, as following one of its links does).
watch(
  () => route.fullPath,
  () => {
    if (open.value) close();
    void bell.refresh();
  },
);
</script>

<template>
  <div ref="root" class="bell" @keydown="onKeydown" @focusout="onFocusout">
    <button
      ref="button"
      type="button"
      class="bell-btn"
      :aria-label="label"
      :title="label"
      :aria-expanded="open"
      :aria-controls="open ? panelId : undefined"
      data-testid="notification-bell"
      @click="toggle"
    >
      <Icon name="bell" />
      <span v-if="badge" class="bell-badge" aria-hidden="true">{{ badge }}</span>
    </button>

    <Transition name="bell-pop">
      <section
        v-if="open"
        :id="panelId"
        class="bell-panel"
        role="region"
        aria-labelledby="bell-heading"
      >
        <div class="bell-head">
          <h2 id="bell-heading" ref="heading" tabindex="-1" class="bell-title">Notifications</h2>
          <button
            v-if="bell.items.value.length"
            type="button"
            class="btn btn-link btn-sm px-1"
            @click="markAll"
          >
            Mark all read
          </button>
        </div>

        <p v-if="bell.error.value" class="bell-empty" role="alert">
          {{ bell.error.value }}
          <button type="button" class="btn btn-link btn-sm p-0" @click="bell.refresh()">
            Try again
          </button>
        </p>
        <p v-else-if="!bell.loaded.value" class="bell-empty" role="status">Loading…</p>
        <p v-else-if="!bell.items.value.length" class="bell-empty">
          Nothing yet. When someone asks you to go along, or answers your ask, it shows here.
        </p>

        <ul v-else class="bell-list">
          <li
            v-for="item in bell.items.value"
            :key="item.notification_id"
            :ref="itemRef(item.notification_id)"
            tabindex="-1"
            class="bell-item"
            :class="{ unread: !item.read || fresh.has(item.notification_id) }"
          >
            <p class="bell-meta">
              <span class="bell-group">{{ item.group_label }}</span>
              <time :datetime="item.created_at">{{ relativeTime(item.created_at, now) }}</time>
              <span v-if="!item.read || fresh.has(item.notification_id)" class="bell-new">
                New<span class="visually-hidden">, unread</span>
              </span>
            </p>
            <p class="bell-text">
              <RouterLink
                v-if="notificationLink(item)"
                :to="notificationLink(item)!"
                @click="follow"
              >
                {{ notificationSentence(item) }}
              </RouterLink>
              <template v-else>{{ notificationSentence(item) }}</template>
            </p>
            <!-- An ask you received that has ended: how, so it no longer reads as a question. -->
            <p v-if="askOutcome(item)" class="bell-outcome" data-testid="ask-outcome">
              <Icon
                :name="item.ask_state === 'accepted' ? 'check-circle' : 'info'"
                class="me-1"
              />{{ askOutcome(item) }}
            </p>
            <div v-if="canAnswer(item)" class="bell-answers">
              <button
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="answering !== null"
                :aria-label="`Yes, I’ll go to ${item.appointment_title}`"
                @click="answer(item, true)"
              >
                <Icon name="user-check" class="me-1" />Yes, I’ll go
              </button>
              <button
                type="button"
                class="btn btn-outline-secondary btn-sm"
                :disabled="answering !== null"
                :aria-label="`Can’t go to ${item.appointment_title}`"
                @click="answer(item, false)"
              >
                <Icon name="user-x" class="me-1" />Can’t go
              </button>
            </div>
          </li>
        </ul>

        <button
          v-if="bell.hasOlder.value"
          type="button"
          class="btn btn-outline-secondary btn-sm w-100 mt-2"
          :disabled="bell.loadingMore.value"
          @click="bell.showOlder()"
        >
          Show older
        </button>
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.bell {
  position: relative;
}

/* The same quiet round button as Settings beside it. */
.bell-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.75rem;
  height: 2.75rem;
  border: 1px solid var(--sl-glass-border);
  border-radius: 50%;
  background: transparent;
  color: var(--sl-ink-soft);
  font-size: 1.15rem;
  transition:
    background-color var(--sl-dur-base) ease,
    color var(--sl-dur-base) ease;
}

.bell-btn:hover,
.bell-btn[aria-expanded='true'] {
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink);
}

/* The count: coral with its own text colour, ringed so it stands off the frosted header. */
.bell-badge {
  position: absolute;
  top: -0.2rem;
  right: -0.2rem;
  min-width: 1.25rem;
  height: 1.25rem;
  padding: 0 0.3rem;
  border-radius: 999px;
  background: var(--sl-coral);
  box-shadow: 0 0 0 2px var(--sl-surface);
  color: var(--sl-coral-on);
  font-size: 0.72rem;
  font-weight: 800;
  line-height: 1.25rem;
  text-align: center;
}

.bell-panel {
  position: absolute;
  z-index: 2;
  top: calc(100% + 0.5rem);
  right: 0;
  width: 24rem;
  max-width: calc(100vw - 1.5rem);
  max-height: min(70vh, 34rem);
  overflow-y: auto;
  padding: 0.85rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  box-shadow: var(--sl-elev-2);
  color: var(--sl-ink);
  text-align: left;
  transform-origin: top right;
}

/* A phone: the full width of the screen under the header, whatever sits right of the bell. */
@media (max-width: 575.98px) {
  .bell {
    position: static;
  }

  .bell-panel {
    position: fixed;
    top: calc(var(--sl-pinned-height, 3.75rem) + 0.25rem);
    right: 0.75rem;
    left: 0.75rem;
    width: auto;
    max-width: none;
  }
}

.bell-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.bell-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 800;
}

.bell-title:focus {
  outline: none;
}

.bell-empty {
  margin: 0.25rem 0;
  color: var(--sl-ink-soft);
}

.bell-list {
  display: grid;
  gap: 0.4rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.bell-item {
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
}

/* Unread: a tinted card and a "New" word, so it never depends on the colour. */
.bell-item.unread {
  border-left: 4px solid var(--sl-jade);
  background: var(--sl-jade-soft);
}

.bell-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem 0.5rem;
  margin: 0 0 0.2rem;
  color: var(--sl-ink-soft);
  font-size: 0.8rem;
}

.bell-group {
  font-weight: 700;
}

.bell-new {
  padding: 0 0.45rem;
  border-radius: 999px;
  background: var(--sl-jade);
  color: var(--sl-jade-on);
  font-weight: 700;
}

.bell-text {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.bell-text a {
  color: inherit;
}

.bell-answers {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.5rem;
}

/* "Can't go" on the tinted unread card: its own surface and a clear edge (well over 3:1). */
.bell-answers .btn-outline-secondary {
  --bs-btn-bg: var(--sl-surface);
  --bs-btn-border-color: var(--sl-ink-soft);
  --bs-btn-color: var(--sl-ink);
}

.bell-outcome {
  display: flex;
  align-items: center;
  margin: 0.35rem 0 0;
  color: var(--sl-ink-soft);
  font-size: 0.875rem;
  font-weight: 700;
}

.bell-answers .btn {
  display: inline-flex;
  flex: 1 1 8rem;
  align-items: center;
  justify-content: center;
  min-height: 2.75rem;
  font-weight: 700;
}

.bell-pop-enter-active,
.bell-pop-leave-active {
  transition:
    opacity var(--sl-dur-base) ease,
    transform var(--sl-dur-base) var(--sl-ease);
}

.bell-pop-enter-from,
.bell-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}
</style>
