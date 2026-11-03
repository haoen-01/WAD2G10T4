<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useAssistant } from '@/composables/useAssistant';
import { acceptNotice, noticeAccepted, useSpeechInput } from '@/composables/useSpeechInput';

/**
 * Where she writes (or says) a question. Enter sends, Shift + Enter starts a new line. The
 * microphone types what she says into the box; she can check it, then press Send.
 */
const props = defineProps<{ busy: boolean }>();
const emit = defineEmits<{ send: [text: string] }>();

const assistant = useAssistant();
const draft = ref('');
const box = ref<HTMLTextAreaElement | null>(null);
const voice = useSpeechInput();
const asking = ref(false);
/** What was in the box before she started speaking, so the words are added after it. */
let before = '';

const canSend = computed(() => draft.value.trim().length > 0 && !props.busy);

function grow() {
  const el = box.value;
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
}
watch(draft, () => void nextTick(grow));

function send() {
  if (!canSend.value) return;
  // Words still being heard must not come back into the box after it is sent.
  if (voice.listening.value) voice.cancel();
  emit('send', draft.value);
  draft.value = '';
}

function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send();
  }
}

function listen() {
  before = draft.value.trim();
  assistant.setMood('listening');
  voice.start((heard) => {
    draft.value = before ? `${before} ${heard}` : heard;
  });
}

function mic() {
  if (voice.listening.value) {
    voice.stop();
    return;
  }
  if (!noticeAccepted()) {
    asking.value = true;
    return;
  }
  listen();
}

function agree() {
  acceptNotice();
  asking.value = false;
  listen();
}

watch(voice.listening, (on) => {
  if (on) return;
  // Back to calm, unless an answer is already on its way.
  if (!assistant.busy.value) assistant.setMood('idle');
  box.value?.focus();
});

defineExpose({
  focus: () => box.value?.focus(),
  /** A suggestion tapped: ask it straight away. */
  fill: (text: string) => emit('send', text),
});
</script>

<template>
  <div class="ask">
    <div v-if="asking" class="ask-notice" role="dialog" aria-labelledby="voice-notice-title">
      <p id="voice-notice-title" class="fw-bold mb-1"><Icon name="speaker" /> Voice typing</p>
      <p class="mb-2">
        Your browser sends what you say to its speech service (Google or Apple) to turn it into
        words. They appear here first, and nothing is sent to Care+ until you press Send.
      </p>
      <div class="d-flex gap-2 flex-wrap">
        <button type="button" class="btn btn-sm ask-yes" data-testid="voice-agree" @click="agree">
          Use my voice
        </button>
        <button type="button" class="btn btn-sm btn-link" @click="asking = false">Not now</button>
      </div>
    </div>

    <p v-if="voice.error.value" class="ask-error" role="status">{{ voice.error.value }}</p>
    <p v-else-if="voice.listening.value" class="ask-listening" role="status">
      <span class="ask-dot" aria-hidden="true"></span> Listening… tap the microphone to stop.
    </p>

    <form class="ask-row" @submit.prevent="send">
      <label for="assistant-input" class="visually-hidden">Your question</label>
      <textarea
        id="assistant-input"
        ref="box"
        v-model="draft"
        class="ask-box"
        rows="1"
        maxlength="2000"
        placeholder="Ask Kaki anything…"
        data-testid="assistant-input"
        @keydown="keydown"
      ></textarea>
      <button
        v-if="voice.supported"
        type="button"
        class="ask-icon ask-mic"
        :class="{ 'is-on': voice.listening.value }"
        :aria-pressed="voice.listening.value"
        :aria-label="voice.listening.value ? 'Stop voice typing' : 'Type with your voice'"
        data-testid="assistant-mic"
        @click="mic"
      >
        <Icon name="mic" />
      </button>
      <button
        type="submit"
        class="ask-icon ask-send"
        :disabled="!canSend"
        aria-label="Send"
        data-testid="assistant-send"
      >
        <Icon name="send" />
      </button>
    </form>
  </div>
</template>

<style scoped>
.ask {
  padding: 0.65rem 0.75rem 0.75rem;
  border-top: 1px solid var(--as-line);
}
.ask-row {
  display: flex;
  align-items: flex-end;
  gap: 0.4rem;
  padding: 0.3rem 0.3rem 0.3rem 0.85rem;
  border: 1px solid var(--as-line);
  border-radius: 1.4rem;
  background: var(--as-field);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.ask-row:focus-within {
  border-color: var(--as-accent);
  box-shadow: 0 0 0 3px var(--as-ring);
}
.ask-box {
  flex: 1;
  min-width: 0;
  max-height: 132px;
  padding: 0.55rem 0;
  border: 0;
  outline: none;
  resize: none;
  background: transparent;
  color: var(--as-ink);
  font-size: 1em;
  line-height: 1.4;
}
.ask-box::placeholder {
  color: var(--as-soft);
}
.ask-icon {
  display: inline-grid;
  place-items: center;
  flex: none;
  width: 2.75rem;
  height: 2.75rem;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--as-soft);
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    transform 0.15s ease;
}
.ask-icon:focus-visible {
  outline: 3px solid var(--as-accent);
  outline-offset: 2px;
}
.ask-mic:hover {
  background: var(--as-hover);
  color: var(--as-ink);
}
.ask-mic.is-on {
  background: #d93a4a;
  color: #fff;
  animation: ask-pulse 1.2s ease-in-out infinite;
}
.ask-send {
  background: var(--as-accent);
  color: var(--as-on-accent);
}
.ask-send:not(:disabled):hover {
  transform: scale(1.06);
}
.ask-send:disabled {
  background: var(--as-hover);
  color: var(--as-soft);
}
.ask-notice {
  margin-bottom: 0.6rem;
  padding: 0.75rem 0.85rem;
  border: 1px solid var(--as-line);
  border-radius: 1rem;
  background: var(--as-field);
  color: var(--as-ink);
  font-size: 0.9em;
}
.ask-yes {
  background: var(--as-accent);
  color: var(--as-on-accent);
  border-radius: 999px;
  font-weight: 700;
}
.ask-listening,
.ask-error {
  margin: 0 0 0.5rem;
  font-size: 0.85em;
  color: var(--as-soft);
}
.ask-error {
  color: var(--as-warn);
}
.ask-dot {
  display: inline-block;
  width: 0.55rem;
  height: 0.55rem;
  margin-right: 0.25rem;
  border-radius: 50%;
  background: #d93a4a;
  animation: ask-pulse 1.2s ease-in-out infinite;
}
@keyframes ask-pulse {
  50% {
    box-shadow: 0 0 0 6px rgb(217 58 74 / 18%);
  }
}
</style>
