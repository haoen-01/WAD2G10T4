import { onBeforeUnmount, onMounted, ref } from 'vue';

/**
 * The current time, refreshed every half minute while the screen using it is open: enough for a
 * greeting and "next task in 25 minutes" to stay true without re-rendering every second.
 */
export function useNow(intervalMs = 30_000) {
  const now = ref(new Date());
  let timer: number | undefined;
  onMounted(() => {
    timer = window.setInterval(() => {
      now.value = new Date();
    }, intervalMs);
  });
  onBeforeUnmount(() => window.clearInterval(timer));
  return now;
}
