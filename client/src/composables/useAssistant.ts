import { computed, ref, shallowRef } from 'vue';

import {
  expandQuestion,
  forApi,
  type ChatMessage,
  type ReplySource,
  type Viewer,
} from '@/lib/assistant-chat';
import { askAssistant } from '@/services/careApi';

/**
 * Kaki, the Care+ assistant: one conversation shared by every screen (a module singleton), so it
 * carries on across pages and when the chat is minimised. It is kept in memory only: nothing of
 * the conversation is stored in the browser, and a reload starts afresh.
 *
 * Questions go to the API (`POST /v1/assistant/chat`), which answers from OpenAI with the server's
 * key or from its built-in helper. The assistant only explains; it never changes anything.
 */

export const ASSISTANT_NAME = 'Kaki';

export type Mood = 'idle' | 'thinking' | 'responding' | 'error' | 'success' | 'listening';

const messages = ref<ChatMessage[]>([]);
const open = ref(false);
const busy = ref(false);
const mood = ref<Mood>('idle');
const unread = ref(0);
let nextId = 1;
let moodTimer = 0;

export interface AssistantContext {
  viewer: Viewer;
  personId: string | null;
  page: string | null;
}

/**
 * Who is asking, about whom, and on which page, read fresh for each question. The dock supplies it
 * from the current screen; any screen can pass more later (it is sent as `page` today).
 */
const contextOf = shallowRef<() => AssistantContext>(() => ({
  viewer: 'senior',
  personId: null,
  page: null,
}));

function setMood(next: Mood, forMs = 0) {
  window.clearTimeout(moodTimer);
  mood.value = next;
  if (forMs) {
    moodTimer = window.setTimeout(() => {
      mood.value = busy.value ? 'thinking' : 'idle';
    }, forMs);
  }
}

function add(role: ChatMessage['role'], content: string, extra: Partial<ChatMessage> = {}) {
  messages.value = [...messages.value, { id: nextId++, role, content, at: Date.now(), ...extra }];
}

/** Plain words for a failed request: never a raw error. */
function failureWords(caught: unknown): string {
  const response = (caught as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  if (response?.status === 429 && typeof response.data?.detail === 'string') {
    return response.data.detail;
  }
  return "Sorry, I couldn't reach Care+ just now. Please check the connection and try again.";
}

async function send(text: string): Promise<void> {
  const question = text.trim();
  if (!question || busy.value) return;
  add('user', question);
  busy.value = true;
  setMood('thinking');
  const { viewer, personId, page } = contextOf.value();
  const history = forApi(messages.value).map((turn, i, all) =>
    i === all.length - 1 ? { ...turn, content: expandQuestion(turn.content, page) } : turn,
  );
  const asked = generation;
  try {
    const reply = await askAssistant({
      messages: history,
      person_id: viewer === 'family' ? personId : null,
      page,
    });
    if (asked !== generation) return; // The conversation was cleared while waiting.
    add('assistant', reply.reply, {
      source: reply.source as ReplySource,
      suggestions: reply.suggestions?.length ? reply.suggestions : undefined,
    });
    if (!open.value) unread.value += 1;
    busy.value = false;
    setMood(reply.source === 'safety' ? 'error' : 'responding', 1400);
  } catch (caught) {
    if (asked !== generation) return;
    add('assistant', failureWords(caught), { source: 'error' });
    if (!open.value) unread.value += 1;
    busy.value = false;
    setMood('error', 2200);
  }
}

function clear() {
  generation += 1;
  messages.value = [];
  unread.value = 0;
  busy.value = false;
  setMood('success', 900);
}

/**
 * Forgets the whole conversation: on sign-out, leaving the demo, or another person or senior,
 * so nobody sees (or sends on) what someone else asked.
 */
let generation = 0;
function reset() {
  generation += 1;
  messages.value = [];
  unread.value = 0;
  busy.value = false;
  open.value = false;
  window.clearTimeout(moodTimer);
  mood.value = 'idle';
}

function setOpen(next: boolean) {
  open.value = next;
  if (next) unread.value = 0;
}

// ---- Where Kaki is looking: shared by every set of eyes on screen ----

/** The pointer, in viewport pixels (`known` once it has moved). Only coordinates are kept. */
export const pointer = { x: 0, y: 0, known: false, at: 0 };
/** A brief glance somewhere (a click elsewhere, or `assistantLookAt`). */
export const glance: { x: number; y: number; until: number } = { x: 0, y: 0, until: 0 };
const watchers = new Set<() => void>();

/** Wakes the eyes when there is somewhere new to look. */
export function onLookChange(wake: () => void): () => void {
  watchers.add(wake);
  return () => watchers.delete(wake);
}
function wakeEyes() {
  for (const wake of watchers) wake();
}

export function notePointer(x: number, y: number) {
  Object.assign(pointer, { x, y, known: true, at: performance.now() });
  wakeEyes();
}

/**
 * Makes Kaki look at a point on the screen (viewport pixels) for a moment, then back to the
 * pointer. Other screens can call it to draw the eye to something: `assistantLookAt(x, y)`.
 */
export function assistantLookAt(x: number, y: number, forMs = 800) {
  Object.assign(glance, { x, y, until: performance.now() + forMs });
  wakeEyes();
}

export function useAssistant() {
  return {
    messages,
    open,
    busy,
    mood,
    unread,
    setContext: (provider: () => AssistantContext) => {
      contextOf.value = provider;
    },
    context: () => contextOf.value(),
    hasChatted: computed(() => messages.value.length > 0),
    send,
    clear,
    reset,
    setOpen,
    setMood,
  };
}
