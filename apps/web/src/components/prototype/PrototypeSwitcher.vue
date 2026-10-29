<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';

/**
 * PROTOTYPE chrome, throwaway: a floating bar that cycles `?variant=` (arrows, ← / → keys) and
 * sets any extra query params given as `groups`. Only rendered in dev builds.
 */
const props = defineProps<{
  variants: { key: string; name: string }[];
  current: string;
  groups?: { param: string; value: string; options: { key: string; label: string }[] }[];
}>();
const emit = defineEmits<{ set: [param: string, value: string] }>();

const show = import.meta.env.DEV;

function step(by: number) {
  const keys = props.variants.map((v) => v.key);
  const at = Math.max(0, keys.indexOf(props.current));
  emit('set', 'variant', keys[(at + by + keys.length) % keys.length]);
}

function onKey(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null;
  if (target?.closest('input, textarea, select, [contenteditable]')) return;
  if (event.key === 'ArrowLeft') step(-1);
  if (event.key === 'ArrowRight') step(1);
}

onMounted(() => window.addEventListener('keydown', onKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onKey));
</script>

<template>
  <div v-if="show" class="proto-bar" role="toolbar" aria-label="Prototype controls">
    <div class="proto-row">
      <button type="button" aria-label="Previous variant" @click="step(-1)">‹</button>
      <strong>
        {{ current }}
        <span class="fw-normal">({{ variants.find((v) => v.key === current)?.name }})</span>
      </strong>
      <button type="button" aria-label="Next variant" @click="step(1)">›</button>
    </div>
    <div v-for="group in groups" :key="group.param" class="proto-row proto-chips">
      <button
        v-for="option in group.options"
        :key="option.key"
        type="button"
        :class="{ on: option.key === group.value }"
        :aria-pressed="option.key === group.value"
        @click="emit('set', group.param, option.key)"
      >
        {{ option.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.proto-bar {
  position: fixed;
  z-index: 2000;
  bottom: calc(var(--sl-tabbar-height, 0px) + 0.75rem);
  left: 50%;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-width: calc(100vw - 1rem);
  padding: 0.5rem 0.75rem;
  border-radius: 1rem;
  background: #111;
  box-shadow: 0 6px 24px rgb(0 0 0 / 0.35);
  color: #fff;
  font:
    13px/1.2 system-ui,
    sans-serif;
  transform: translateX(-50%);
}

.proto-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
}

.proto-bar button {
  padding: 0.2rem 0.6rem;
  border: 1px solid #555;
  border-radius: 999px;
  background: transparent;
  color: #fff;
}

.proto-chips button.on {
  border-color: #ffd54a;
  background: #ffd54a;
  color: #111;
}
</style>
