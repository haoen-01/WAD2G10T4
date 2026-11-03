<script setup lang="ts">
import { computed, onMounted, ref, toRef, watch } from 'vue';

import BadgeTile from '@/components/badges/BadgeTile.vue';
import BadgeViewer from '@/components/badges/BadgeViewer.vue';
import Icon from '@/components/ui/Icon.vue';
import { useBadges, type ShelfBadge } from '@/composables/useBadges';
import { shelfSummary, type BadgeGroup } from '@/lib/badges';

/**
 * The walking badges, grouped: this month's challenge, one-day goals, habits, milestones and walks.
 * On the senior's own page she claims what she has earned; the family sees the same shelf to
 * cheer her on, without a Claim button.
 */
const props = defineProps<{
  personId: string;
  canClaim: boolean;
  seniorName: string;
  /** "My walking badges" on her page, "Mdm Lim's walking badges" for the family. */
  title: string;
}>();

const shelf = useBadges(toRef(props, 'personId'));
const openId = ref<string | null>(null);
/** The medal on the shelf the open one flew out of (and flies back to). */
const origin = ref<HTMLElement | null>(null);
/** Whether the badge just opened is being seen for the first time since it was claimed. */
const firstLook = ref(false);
const audience = computed(() => (props.canClaim ? 'self' : 'family'));
const celebrating = ref<string[]>([]);
const announcement = ref('');
let celebrationTimer = 0;

onMounted(() => {
  if (!shelf.loaded.value) void shelf.load();
});
watch(
  () => props.personId,
  () => {
    if (!shelf.loaded.value) void shelf.load();
  },
);

const GROUPS: { id: BadgeGroup; title: string; note: string }[] = [
  {
    id: 'challenge',
    title: 'Monthly challenge',
    note: 'A new goal each month, set from a usual day.',
  },
  { id: 'day', title: 'One-day goals', note: 'Steps walked in a single day.' },
  { id: 'habit', title: 'Habits', note: 'Walking days, a little and often.' },
  { id: 'milestone', title: 'Milestones', note: 'Every step adds up.' },
  { id: 'walk', title: 'Walks', note: 'Walks finished on the Walk page while shared.' },
];

const groups = computed(() =>
  GROUPS.map((group) => ({
    ...group,
    badges: shelf.badges.value.filter((badge) => badge.group === group.id),
  })).filter((group) => group.badges.length > 0),
);

const open = computed<ShelfBadge | null>(
  () => shelf.badges.value.find((badge) => badge.id === openId.value) ?? null,
);
const ready = computed(() => shelf.badges.value.filter((badge) => badge.state === 'ready'));

function openUp(id: string, from: HTMLElement) {
  origin.value = from;
  firstLook.value = shelf.firstLook(id, audience.value);
  openId.value = id;
}

/** Closed: focus goes back to the badge it was opened from. */
function shut() {
  const from = origin.value;
  openId.value = null;
  from?.closest('li')?.querySelector<HTMLElement>('.tile-open')?.focus();
}

function celebrate(ids: string[]) {
  window.clearTimeout(celebrationTimer);
  celebrating.value = ids;
  celebrationTimer = window.setTimeout(() => {
    celebrating.value = [];
  }, 1800);
}

function claim(id: string) {
  const badge = shelf.badges.value.find((item) => item.id === id);
  if (!badge || !shelf.claim(id)) return;
  celebrate([id]);
  announcement.value = `Well done! You claimed ${badge.name}.`;
}

function claimAll() {
  const ids = ready.value.map((badge) => badge.id);
  const at = Date.now();
  for (const id of ids) shelf.claim(id, at);
  celebrate(ids);
  announcement.value = `Well done! You claimed ${ids.length} ${ids.length === 1 ? 'badge' : 'badges'}.`;
}
</script>

<template>
  <section
    class="badge-shelf sl-panel"
    aria-labelledby="badge-shelf-title"
    data-testid="badge-shelf"
  >
    <header class="shelf-head">
      <div>
        <h2 id="badge-shelf-title" class="h3 mb-1">
          <Icon name="star" class="shelf-icon" />{{ title }}
        </h2>
        <p class="sl-note mb-0" data-testid="badge-summary">
          {{
            shelf.loaded.value || shelf.failed.value
              ? shelfSummary(shelf.badges.value)
              : canClaim
                ? 'Reading your steps…'
                : `Reading ${seniorName}’s steps…`
          }}
          <template v-if="ready.length">
            ·
            {{
              canClaim
                ? `${ready.length} ready to claim`
                : `${ready.length} waiting for ${seniorName} to claim`
            }}
          </template>
        </p>
      </div>
      <button
        v-if="canClaim && ready.length > 1"
        type="button"
        class="btn shelf-claim-all"
        data-testid="claim-all"
        @click="claimAll"
      >
        <Icon name="sparkle" /> Claim all {{ ready.length }}
      </button>
    </header>

    <p v-if="shelf.failed.value" class="shelf-failed" role="status">
      <Icon name="alert" /> Couldn’t read the steps just now, so only badges already earned and walk
      badges are shown.
      <button type="button" class="btn btn-link p-0 align-baseline" @click="shelf.load()">
        Try again
      </button>
    </p>

    <div v-for="group in groups" :key="group.id" class="shelf-group">
      <h3 class="shelf-group-title h6 mb-0">{{ group.title }}</h3>
      <p class="sl-note mb-2">{{ group.note }}</p>
      <ul class="shelf-grid list-unstyled mb-0">
        <BadgeTile
          v-for="badge in group.badges"
          :key="badge.id"
          :badge="badge"
          :can-claim="canClaim"
          :celebrating="celebrating.includes(badge.id)"
          :owner="seniorName"
          :away="openId === badge.id"
          @open="(from) => openUp(badge.id, from)"
          @claim="claim(badge.id)"
        />
      </ul>
    </div>

    <p class="shelf-foot sl-note mb-0">
      <Icon name="info" /> Badges are just for fun. Missing a day never takes one away, and they
      never change what Care+ suggests.
    </p>

    <p class="visually-hidden" role="status" aria-live="polite" data-testid="badge-announce">
      {{ announcement }}
    </p>

    <BadgeViewer
      :badge="open"
      :can-claim="canClaim"
      :who="canClaim ? 'You' : seniorName"
      :owner="seniorName"
      :origin="origin"
      :first-look="firstLook"
      @close="shut"
      @seen="(id) => shelf.markSeen(id, audience)"
      @claim="claim"
    />
  </section>
</template>

<style scoped>
.badge-shelf {
  border-top: 0.35rem solid #c4953a;
}
.shelf-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.shelf-icon {
  width: 1.1em;
  height: 1.1em;
  margin-right: 0.45rem;
  vertical-align: -0.15em;
  color: #c4953a;
}
.shelf-claim-all {
  min-height: 48px;
  border: 0;
  border-radius: 999px;
  background: linear-gradient(135deg, #f8e3a0, #c4953a 55%, #8a6418);
  color: #2e1f03;
  font-weight: 800;
  box-shadow: 0 4px 12px rgb(138 100 24 / 30%);
}
.shelf-claim-all:focus-visible {
  outline: 3px solid var(--sl-focus);
  outline-offset: 2px;
}
.shelf-failed {
  padding: 0.75rem 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-coral-soft);
  color: var(--sl-coral-deep);
}
.shelf-group + .shelf-group {
  margin-top: 1.5rem;
  padding-top: 1.25rem;
  border-top: 1px solid var(--sl-line);
}
.shelf-group-title {
  font-weight: 800;
  letter-spacing: 0.02em;
}
.shelf-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
  gap: 0.5rem 0.75rem;
}
@media (max-width: 420px) {
  .shelf-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.shelf-foot {
  display: flex;
  gap: 0.5rem;
  align-items: flex-start;
  margin-top: 1.5rem;
}
</style>
