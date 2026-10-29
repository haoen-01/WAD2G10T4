<script setup lang="ts">
/**
 * PROTOTYPE B, throwaway. "Groups tab": on desktop a left sidebar lists your groups (always
 * visible, one click to switch) with the page links under it; on a phone the tab bar gains a fifth
 * "Groups" tab. The groups page is a big radio list (pick = switch) with the picked group's
 * details under it. The Link card is a slim banner on Home, plus locked tiles where steps, the
 * watch and suggestions would be.
 */
import { computed, ref } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import Icon from '@/components/ui/Icon.vue';

import { seniorName, type ProtoGroup, type ProtoScreen } from './mock';

const props = defineProps<{ groups: ProtoGroup[]; currentId: string; screen: ProtoScreen }>();
const emit = defineEmits<{ select: [id: string]; link: [id: string]; go: [screen: ProtoScreen] }>();

const current = computed(() => props.groups.find((g) => g.id === props.currentId) ?? null);
const active = computed(() => props.groups.filter((g) => g.myStatus === 'active'));
const pending = computed(() => props.groups.filter((g) => g.myStatus === 'pending'));
const linking = ref(false);
const pin = ref('');

const TABS = [
  { label: 'Home', icon: 'home', screen: 'home' },
  { label: 'Walk', icon: 'walk', screen: null },
  { label: 'Calendar', icon: 'calendar', screen: null },
  { label: 'Family', icon: 'users', screen: null },
  { label: 'Groups', icon: 'people', screen: 'groups' },
] as const;

function initials(name: string) {
  return name
    .split(' ')
    .slice(0, 2)
    .map((p) => p[0])
    .join('');
}
</script>

<template>
  <div class="b-shell">
    <!-- ===== desktop sidebar ===== -->
    <aside class="b-side d-none d-md-flex">
      <span class="brand-mini mb-3">Care<b>+</b></span>
      <p class="small text-body-secondary mb-1">Caring for</p>
      <button
        v-for="g in active"
        :key="g.id"
        type="button"
        class="b-group"
        :class="{ on: g.id === currentId }"
        @click="emit('select', g.id)"
      >
        <span class="b-face" :class="{ 'is-unlinked': !g.linkedName }">{{
          initials(seniorName(g))
        }}</span>
        <span class="text-start">
          {{ seniorName(g) }}
          <span v-if="!g.linkedName" class="d-block small text-warning-emphasis"
            >not linked yet</span
          >
        </span>
      </button>
      <div v-for="g in pending" :key="g.id" class="b-group is-pending">
        <span class="b-face"><Icon name="clock" /></span>
        <span>{{ seniorName(g) }} <span class="d-block small">waiting to be let in</span></span>
      </div>
      <button type="button" class="b-group b-add" @click="emit('go', 'groups')">
        <span class="b-face"><Icon name="plus" /></span> Groups &amp; invites
      </button>
      <hr />
      <button
        v-for="t in TABS.slice(0, 4)"
        :key="t.label"
        type="button"
        class="b-link"
        :class="{ on: t.screen === screen }"
        @click="t.screen && emit('go', t.screen)"
      >
        <Icon :name="t.icon" /> {{ t.label }}
      </button>
    </aside>

    <!-- ===== phone top bar + 5-tab bar ===== -->
    <header class="b-phonehead d-md-none">
      <span class="brand-mini">Care<b>+</b></span>
      <span class="small ms-auto">{{ current ? seniorName(current) : '' }}</span>
    </header>
    <nav class="b-tabs d-md-none">
      <button
        v-for="t in TABS"
        :key="t.label"
        type="button"
        :class="{ on: t.screen === screen }"
        @click="t.screen && emit('go', t.screen)"
      >
        <span class="position-relative">
          <Icon :name="t.icon" />
          <span v-if="t.label === 'Groups' && pending.length" class="b-dot" />
        </span>
        <span>{{ t.label }}</span>
      </button>
    </nav>

    <main class="b-main">
      <!-- ===== groups page ===== -->
      <section v-if="screen === 'groups'">
        <h1 class="h2">Who are you caring for?</h1>
        <fieldset class="mb-4">
          <legend class="visually-hidden">Pick a family group</legend>
          <label
            v-for="g in active"
            :key="g.id"
            class="b-radio"
            :class="{ on: g.id === currentId }"
          >
            <input
              type="radio"
              name="b-group"
              class="form-check-input"
              :checked="g.id === currentId"
              @change="emit('select', g.id)"
            />
            <span class="b-face b-face-lg" :class="{ 'is-unlinked': !g.linkedName }">{{
              initials(seniorName(g))
            }}</span>
            <span class="me-auto">
              <strong class="d-block">{{ seniorName(g) }}</strong>
              <span class="small text-body-secondary">
                {{ g.members.length }} in the family ·
                {{ g.myRole === 'owner' ? 'you started it' : 'member' }}
                <template v-if="!g.linkedName"> · not linked yet</template>
              </span>
            </span>
          </label>
          <div v-for="g in pending" :key="g.id" class="b-radio is-pending">
            <span class="b-face b-face-lg"><Icon name="clock" /></span>
            <span class="me-auto">
              <strong class="d-block">{{ seniorName(g) }}</strong>
              <span class="small">Waiting for someone in the family to let you in</span>
            </span>
            <button type="button" class="btn btn-sm btn-link">Cancel</button>
          </div>
        </fieldset>

        <div v-if="current" class="row g-4">
          <div class="col-12 col-lg-6">
            <div class="sl-panel h-100">
              <h2 class="sl-section-title">Invite to {{ seniorName(current) }}’s family</h2>
              <p class="mb-1 small text-body-secondary">Share this Join PIN</p>
              <p class="display-6 font-monospace mb-2">{{ current.joinPin }}</p>
              <button type="button" class="btn btn-outline-secondary btn-sm">
                <Icon name="share" /> Share
              </button>
            </div>
          </div>
          <div class="col-12 col-lg-6">
            <div class="sl-panel h-100">
              <h2 class="sl-section-title">In the family</h2>
              <p
                v-for="m in current.members"
                :key="m.name"
                class="d-flex align-items-center gap-2 mb-2"
              >
                <MemberAvatar :name="m.name" :colour="m.colour" size="sm" /> {{ m.name }}
                <span class="small text-body-secondary">{{ m.relationship }}</span>
              </p>
            </div>
          </div>
        </div>

        <h2 class="sl-section-title mt-5">Another family</h2>
        <div class="d-flex flex-wrap gap-2">
          <button type="button" class="btn btn-outline-primary">
            <Icon name="key" /> Join with a PIN
          </button>
          <button type="button" class="btn btn-outline-primary">
            <Icon name="plus" /> Create a group
          </button>
        </div>
      </section>

      <!-- ===== family Home (tidied) ===== -->
      <section v-else-if="current">
        <div
          v-if="!current.linkedName"
          class="b-banner d-flex flex-wrap align-items-center gap-2 mb-4"
        >
          <Icon name="link" />
          <span class="me-auto">
            <strong>Link {{ current.typedName }}’s account</strong> to see their steps and watch.
          </span>
          <button v-if="!linking" type="button" class="btn btn-sm btn-dark" @click="linking = true">
            Link now
          </button>
          <form v-else class="d-flex gap-2 w-100" @submit.prevent="emit('link', current.id)">
            <input
              v-model="pin"
              class="form-control"
              inputmode="numeric"
              maxlength="6"
              placeholder="Their Senior-link PIN"
            />
            <button class="btn btn-dark" :disabled="pin.length < 6">Link</button>
          </form>
          <p v-if="linking" class="small mb-0 w-100">
            {{ current.typedName }} finds this PIN on their own Care+ screen. Showing it to you is
            them agreeing to be linked.
          </p>
        </div>

        <h1 class="h3 mb-3">{{ seniorName(current) }} today</h1>
        <div class="row row-cols-1 row-cols-sm-3 g-3 mb-4">
          <div class="col">
            <div class="sl-panel h-100" :class="{ 'b-locked': !current.linkedName }">
              <p class="small text-body-secondary mb-1"><Icon name="activity" /> Steps</p>
              <p v-if="current.linkedName" class="fs-3 mb-0">
                {{ current.steps?.toLocaleString() }}
              </p>
              <p v-else class="mb-0 small"><Icon name="lock" /> After linking</p>
            </div>
          </div>
          <div class="col">
            <div class="sl-panel h-100" :class="{ 'b-locked': !current.linkedName }">
              <p class="small text-body-secondary mb-1"><Icon name="watch" /> Watch</p>
              <p v-if="current.linkedName" class="mb-0 small">{{ current.watch }}</p>
              <p v-else class="mb-0 small"><Icon name="lock" /> After linking</p>
            </div>
          </div>
          <div class="col">
            <div class="sl-panel h-100" :class="{ 'b-locked': !current.linkedName }">
              <p class="small text-body-secondary mb-1"><Icon name="sparkle" /> Suggestion</p>
              <p v-if="current.linkedName" class="mb-0 small">Tai chi at the AAC, Sat 10 am</p>
              <p v-else class="mb-0 small"><Icon name="lock" /> After linking</p>
            </div>
          </div>
        </div>

        <div class="row g-4">
          <div class="col-12 col-lg-8">
            <div class="sl-panel">
              <h2 class="sl-section-title">Coming up</h2>
              <p class="mb-2"><Icon name="calendar" /> {{ current.nextVisit }}</p>
              <h2 class="sl-section-title mt-3">Tasks</h2>
              <p class="mb-0 text-body-secondary">Buy rice · Top up EZ-Link</p>
            </div>
          </div>
          <div class="col-12 col-lg-4">
            <div class="sl-panel">
              <h2 class="sl-section-title">Check in</h2>
              <button type="button" class="btn btn-outline-primary w-100">
                I was in touch today
              </button>
            </div>
          </div>
        </div>
        <p class="mt-4 small text-body-secondary">
          Activity feed and the week of availability moved to Family.
        </p>
      </section>
    </main>
  </div>
</template>

<style scoped>
.brand-mini {
  font-weight: 800;
  font-size: 1.25rem;
}

.brand-mini b {
  color: var(--sl-sun);
}

.b-shell {
  display: flex;
  gap: 2rem;
}

.b-main {
  flex: 1;
  min-width: 0;
}

.b-side {
  position: sticky;
  top: 1rem;
  flex: 0 0 15rem;
  flex-direction: column;
  align-self: flex-start;
  gap: 0.25rem;
  padding: 1rem;
  border: 1px solid var(--sl-line);
  border-radius: 1rem;
}

.b-group,
.b-link {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  min-height: 2.75rem;
  padding: 0.35rem 0.5rem;
  border: 0;
  border-radius: 0.6rem;
  background: none;
  text-align: left;
}

.b-group.on,
.b-link.on {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
  font-weight: 700;
}

.b-group.is-pending,
.b-radio.is-pending {
  color: var(--bs-secondary-color);
}

.b-add {
  color: var(--sl-jade-deep);
}

.b-face {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 50%;
  background: var(--sl-ink);
  color: var(--sl-on-ink);
  font-size: 0.8rem;
  font-weight: 700;
}

.b-face.is-unlinked {
  border: 2px dashed var(--sl-sun);
  background: transparent;
  color: var(--sl-ink);
}

.b-face-lg {
  width: 3rem;
  height: 3rem;
}

.b-radio {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  margin-bottom: 0.5rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--sl-line);
  border-radius: 0.9rem;
  cursor: pointer;
}

.b-radio.on {
  border: 2px solid var(--sl-jade);
}

.b-radio.is-pending {
  border-style: dashed;
  cursor: default;
}

.b-phonehead {
  display: flex;
  align-items: center;
  margin: 0 0 1rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--sl-line);
}

.b-tabs {
  position: fixed;
  z-index: 20;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  border-top: 1px solid var(--sl-line);
  background: var(--bs-body-bg);
}

.b-tabs button {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  padding: 0.5rem 0;
  border: 0;
  background: none;
  font-size: 0.75rem;
}

.b-tabs button.on {
  color: var(--sl-jade-deep);
  font-weight: 700;
}

.b-dot {
  position: absolute;
  top: -2px;
  right: -6px;
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--sl-sun);
}

.b-banner {
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  background: var(--sl-sun);
  color: #1b1b1b;
}

.b-locked {
  border-style: dashed;
  color: var(--bs-secondary-color);
}
</style>
