import { usePreferredReducedMotion } from '@vueuse/core';
import { computed } from 'vue';

/**
 * Whether the person asked their device for less motion. Every component in `components/motion`
 * reads this and falls back to an instant change or a plain fade. (The CSS rule in `theme.css`
 * only covers CSS transitions, not Motion for Vue's JavaScript animations.)
 */
export function useReducedMotion() {
  const preference = usePreferredReducedMotion();
  return computed(() => preference.value === 'reduce');
}
