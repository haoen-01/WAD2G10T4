import { ref } from 'vue';

/**
 * How tall (px) the senior's section bar is while it is fixed to the bottom of a phone screen, and
 * 0 when it is not (a wide screen, or another page). `views/SeniorView.vue` measures it (it grows
 * with the text size, and takes a second row when the tabs no longer fit side by side);
 * `components/assistant/AssistantDock.vue` keeps Kaki above it. Plain Vue, no motion.
 */
export const seniorTabBarHeight = ref(0);
