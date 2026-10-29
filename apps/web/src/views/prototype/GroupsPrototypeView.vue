<script setup lang="ts">
/**
 * PROTOTYPE (issue #18), throwaway. Three variants of the groups page, the Switch group control
 * and the "Link {senior}'s account" card, plus family Home after the tidy-up (activity feed and the
 * week of availability moved to the Family page), on `/groups/prototype` (dev builds only).
 *
 *   ?variant=A|B|C   ?state=one|two|pending|nosenior   ?screen=groups|home
 *
 * The real header and tab bar are hidden here; each variant draws its own mock header so the
 * switcher can be judged in place. Everything is in memory; nothing calls the API.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import PrototypeSwitcher from '@/components/prototype/PrototypeSwitcher.vue';

import {
  FIXTURES,
  SCREENS,
  STATES,
  type ProtoGroup,
  type ProtoScreen,
  type ProtoState,
} from './groups/mock';
import VariantA from './groups/VariantA.vue';
import VariantB from './groups/VariantB.vue';
import VariantC from './groups/VariantC.vue';

const VARIANTS = [
  { key: 'A', name: 'Name chip in header · card list' },
  { key: 'B', name: 'Groups tab · sidebar on desktop' },
  { key: 'C', name: 'Avatar rail · settings list' },
];

const route = useRoute();
const router = useRouter();

const variant = computed(() => {
  const raw = String(route.query.variant ?? 'A').toUpperCase();
  return VARIANTS.some((v) => v.key === raw) ? raw : 'A';
});
const state = computed<ProtoState>(() => {
  const raw = String(route.query.state ?? 'one');
  return STATES.some((s) => s.key === raw) ? (raw as ProtoState) : 'one';
});
const screen = computed<ProtoScreen>(() => (route.query.screen === 'home' ? 'home' : 'groups'));

// A fresh in-memory copy per state, so "linking" or switching never leaks between states.
const groups = ref<ProtoGroup[]>([]);
const currentId = ref('');
watch(
  state,
  (next) => {
    groups.value = structuredClone(FIXTURES[next]);
    currentId.value = groups.value.find((g) => g.myStatus === 'active')?.id ?? '';
  },
  { immediate: true },
);

function set(param: string, value: string) {
  void router.replace({ query: { ...route.query, [param]: value } });
}

function select(id: string) {
  currentId.value = id;
}

/** Stub for "the senior showed their Senior-link PIN": the typed name becomes their account name. */
function link(id: string) {
  const group = groups.value.find((g) => g.id === id);
  if (!group) return;
  group.linkedName = 'Ong Siew Hwa';
  group.steps = 2650;
  group.usualSteps = 3000;
  group.watch = 'Worn 6 h today · synced just now';
}

const props = computed(() => ({
  groups: groups.value,
  currentId: currentId.value,
  screen: screen.value,
}));

onMounted(() => document.body.classList.add('proto-hide-shell'));
onBeforeUnmount(() => document.body.classList.remove('proto-hide-shell'));
</script>

<template>
  <div class="proto-host">
    <p class="proto-flag">PROTOTYPE · #18 · throwaway</p>
    <VariantA
      v-if="variant === 'A'"
      v-bind="props"
      @select="select"
      @link="link"
      @go="set('screen', $event)"
    />
    <VariantB
      v-else-if="variant === 'B'"
      v-bind="props"
      @select="select"
      @link="link"
      @go="set('screen', $event)"
    />
    <VariantC v-else v-bind="props" @select="select" @link="link" @go="set('screen', $event)" />

    <details class="proto-state small mt-5">
      <summary>State</summary>
      <pre>{{ { variant, state, screen, currentId, groups } }}</pre>
    </details>

    <PrototypeSwitcher
      :variants="VARIANTS"
      :current="variant"
      :groups="[
        { param: 'state', value: state, options: STATES },
        { param: 'screen', value: screen, options: SCREENS },
      ]"
      @set="set"
    />
  </div>
</template>

<style>
/* The real header and tab bar step aside so each variant's mock header is the only one. */
body.proto-hide-shell .topbar,
body.proto-hide-shell .mainnav--tabs {
  display: none !important;
}
</style>

<style scoped>
.proto-host {
  padding-bottom: 12rem;
}

.proto-flag {
  margin: 0 0 0.5rem;
  color: #b00;
  font:
    700 11px/1 system-ui,
    sans-serif;
  letter-spacing: 0.08em;
}

.proto-state pre {
  max-height: 20rem;
  overflow: auto;
  font-size: 11px;
}
</style>
