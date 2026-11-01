<script setup lang="ts">
import { nextTick, ref, watch } from 'vue';

import AssistantOrb from '@/components/assistant/AssistantOrb.vue';
import { ASSISTANT_NAME } from '@/composables/useAssistant';
import { timeWords, type ChatMessage } from '@/lib/assistant-chat';

/**
 * The conversation: her words on the right, Kaki's on the left, the newest at the bottom, with a
 * "typing" bubble while an answer is on its way and things to ask next under the latest answer.
 * Empty, it says hello and offers a few questions to start with.
 */
const props = defineProps<{
  messages: readonly ChatMessage[];
  busy: boolean;
  greeting: string;
  starters: readonly string[];
}>();
const emit = defineEmits<{ ask: [text: string] }>();

const scroller = ref<HTMLElement | null>(null);

function toBottom() {
  const el = scroller.value;
  if (!el) return;
  const smooth = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
}
watch(
  () => [props.messages.length, props.busy],
  () => void nextTick(toBottom),
);
defineExpose({ toBottom });
</script>

<template>
  <div ref="scroller" class="talk" data-testid="assistant-messages">
    <div v-if="!messages.length" class="talk-hello">
      <AssistantOrb :size="72" />
      <p class="talk-hello-title">{{ greeting }}</p>
      <p class="talk-hello-line">
        Ask about steps and walks, what's coming up, badges, or how to use Care+.
      </p>
      <div class="talk-chips" role="group" aria-label="Questions to start with">
        <button
          v-for="starter in starters"
          :key="starter"
          type="button"
          class="talk-chip"
          data-testid="assistant-chip"
          @click="emit('ask', starter)"
        >
          {{ starter }}
        </button>
      </div>
    </div>

    <ol v-else class="talk-list" role="log" aria-live="polite" aria-label="Conversation">
      <li
        v-for="(message, i) in messages"
        :key="message.id"
        class="talk-item"
        :class="[`is-${message.role}`, { 'is-problem': message.source === 'error' }]"
        :data-testid="`assistant-${message.role}`"
      >
        <span class="visually-hidden">{{ message.role === 'user' ? 'You' : ASSISTANT_NAME }}:</span>
        <div class="talk-bubble">{{ message.content }}</div>
        <span class="talk-time">{{ timeWords(message.at) }}</span>
        <div
          v-if="message.role === 'assistant' && message.suggestions && i === messages.length - 1"
          class="talk-chips talk-next"
          role="group"
          aria-label="Ask next"
        >
          <button
            v-for="next in message.suggestions"
            :key="next"
            type="button"
            class="talk-chip"
            @click="emit('ask', next)"
          >
            {{ next }}
          </button>
        </div>
      </li>
      <li v-if="busy" class="talk-item is-assistant" data-testid="assistant-typing">
        <span class="visually-hidden">{{ ASSISTANT_NAME }} is typing</span>
        <div class="talk-bubble talk-typing" aria-hidden="true">
          <span></span><span></span><span></span>
        </div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.talk {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 1rem 0.9rem 0.5rem;
}
.talk-hello {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1.25rem 0.5rem 0.5rem;
  text-align: center;
}
.talk-hello-title {
  margin: 0.9rem 0 0.25rem;
  font-size: 1.2em;
  font-weight: 800;
  color: var(--as-ink);
}
.talk-hello-line {
  max-width: 19rem;
  margin: 0 0 1rem;
  color: var(--as-soft);
}
.talk-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.45rem;
}
.talk-next {
  justify-content: flex-start;
  margin-top: 0.5rem;
}
.talk-chip {
  min-height: 2.5rem;
  padding: 0.45rem 0.9rem;
  border: 1px solid var(--as-line);
  border-radius: 999px;
  background: var(--as-field);
  color: var(--as-ink);
  font-size: 0.92em;
  font-weight: 600;
  text-align: left;
  transition:
    background-color 0.2s ease,
    border-color 0.2s ease,
    transform 0.15s ease;
}
.talk-chip:hover {
  border-color: var(--as-accent);
  background: var(--as-hover);
  transform: translateY(-1px);
}
.talk-chip:focus-visible {
  outline: 3px solid var(--as-accent);
  outline-offset: 2px;
}
.talk-list {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.talk-item {
  display: flex;
  flex-direction: column;
  max-width: 86%;
  animation: talk-in 0.32s var(--sl-ease) both;
}
.talk-item.is-user {
  align-self: flex-end;
  align-items: flex-end;
}
.talk-item.is-assistant {
  align-self: flex-start;
  align-items: flex-start;
}
.talk-bubble {
  padding: 0.6rem 0.85rem;
  border-radius: 1.1rem;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.is-user .talk-bubble {
  border-bottom-right-radius: 0.35rem;
  background: var(--as-accent);
  color: var(--as-on-accent);
}
.is-assistant .talk-bubble {
  border-bottom-left-radius: 0.35rem;
  background: var(--as-bubble);
  color: var(--as-ink);
}
.is-problem .talk-bubble {
  background: var(--as-warn-soft);
  color: var(--as-warn);
}
.talk-time {
  margin-top: 0.2rem;
  padding: 0 0.3rem;
  color: var(--as-soft);
  font-size: 0.72em;
}
.talk-typing {
  display: inline-flex;
  gap: 0.3rem;
  padding: 0.8rem 0.9rem;
}
.talk-typing span {
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: var(--as-soft);
  animation: talk-dot 1.1s ease-in-out infinite;
}
.talk-typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.talk-typing span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes talk-in {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.98);
  }
}
@keyframes talk-dot {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}
</style>
