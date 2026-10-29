<script setup lang="ts">
/**
 * PROTOTYPE C, throwaway. "Avatar rail": the header and tab bar stay as they are; the switcher is
 * a rail of senior avatars just under the header on every family page (pending = dashed ring,
 * "+" = groups page), hidden with only one group. The groups page is a settings-style list with
 * expanding rows. The Link card is a set-up checklist that replaces the Home hero.
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
const showRail = computed(() => props.groups.length > 1);
const pin = ref('');

const TABS = [
  { label: 'Home', icon: 'home', screen: 'home' },
  { label: 'Walk', icon: 'walk', screen: null },
  { label: 'Calendar', icon: 'calendar', screen: null },
  { label: 'Family', icon: 'users', screen: null },
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
  <div>
    <!-- ===== mock header: unchanged from today ===== -->
    <header class="c-head">
      <span class="brand-mini">Care<b>+</b></span>
      <nav class="c-pill d-none d-md-flex">
        <button
          v-for="t in TABS"
          :key="t.label"
          type="button"
          :class="{ on: t.screen === screen }"
          @click="t.screen && emit('go', t.screen)"
        >
          {{ t.label }}
        </button>
      </nav>
      <button
        type="button"
        class="btn btn-sm btn-link ms-auto ms-md-0"
        @click="emit('go', 'groups')"
      >
        <Icon name="people" /> <span class="d-none d-sm-inline">Groups</span>
      </button>
    </header>
    <nav class="c-tabs d-md-none">
      <button
        v-for="t in TABS"
        :key="t.label"
        type="button"
        :class="{ on: t.screen === screen }"
        @click="t.screen && emit('go', t.screen)"
      >
        <Icon :name="t.icon" /><span>{{ t.label }}</span>
      </button>
    </nav>

    <!-- ===== avatar rail (the switcher) ===== -->
    <div v-if="showRail" class="c-rail" role="radiogroup" aria-label="Whose care to show">
      <button
        v-for="g in active"
        :key="g.id"
        type="button"
        role="radio"
        :aria-checked="g.id === currentId"
        class="c-person"
        :class="{ on: g.id === currentId }"
        @click="emit('select', g.id)"
      >
        <span class="c-face" :class="{ 'is-unlinked': !g.linkedName }">{{
          initials(seniorName(g))
        }}</span>
        <span class="c-name">{{ seniorName(g) }}</span>
      </button>
      <button
        v-for="g in pending"
        :key="g.id"
        type="button"
        class="c-person is-pending"
        @click="emit('go', 'groups')"
      >
        <span class="c-face"><Icon name="clock" /></span>
        <span class="c-name">{{ seniorName(g) }}<br /><small>waiting</small></span>
      </button>
      <button type="button" class="c-person" @click="emit('go', 'groups')">
        <span class="c-face c-plus"><Icon name="plus" /></span>
        <span class="c-name">Add</span>
      </button>
    </div>

    <!-- ===== groups page ===== -->
    <section v-if="screen === 'groups'" class="c-settings">
      <h1 class="h2 mb-4">Family groups</h1>

      <h2 class="c-label">You are in</h2>
      <ul class="c-list">
        <li v-for="g in active" :key="g.id">
          <details :open="g.id === currentId">
            <summary class="c-row">
              <span class="c-face c-face-sm" :class="{ 'is-unlinked': !g.linkedName }">{{
                initials(seniorName(g))
              }}</span>
              <span class="me-auto">
                {{ seniorName(g) }}’s family
                <span v-if="!g.linkedName" class="small text-warning-emphasis d-block"
                  >{{ g.typedName }} is not linked yet</span
                >
              </span>
              <span v-if="g.id === currentId" class="small text-success">Showing</span>
              <Icon name="chevron-down" />
            </summary>
            <div class="c-body">
              <dl class="row mb-2 small">
                <dt class="col-4">Join PIN</dt>
                <dd class="col-8 font-monospace fs-6">{{ g.joinPin }}</dd>
                <dt class="col-4">Members</dt>
                <dd class="col-8">
                  <span
                    v-for="m in g.members"
                    :key="m.name"
                    class="d-inline-flex align-items-center gap-1 me-2"
                  >
                    <MemberAvatar :name="m.name" :colour="m.colour" size="sm" />{{ m.name }}
                  </span>
                </dd>
                <dt class="col-4">You</dt>
                <dd class="col-8">{{ g.myRole === 'owner' ? 'Started this group' : 'Member' }}</dd>
              </dl>
              <div class="d-flex flex-wrap gap-2">
                <button
                  v-if="g.id !== currentId"
                  type="button"
                  class="btn btn-primary btn-sm"
                  @click="emit('select', g.id)"
                >
                  Show this family
                </button>
                <button type="button" class="btn btn-outline-secondary btn-sm">
                  Copy Join PIN
                </button>
                <button type="button" class="btn btn-link btn-sm text-danger">Leave group</button>
              </div>
            </div>
          </details>
        </li>
      </ul>

      <template v-if="pending.length">
        <h2 class="c-label">Waiting to be let in</h2>
        <ul class="c-list">
          <li v-for="g in pending" :key="g.id" class="c-row">
            <span class="c-face c-face-sm"><Icon name="clock" /></span>
            <span class="me-auto">{{ seniorName(g) }}’s family</span>
            <button type="button" class="btn btn-link btn-sm">Cancel</button>
          </li>
        </ul>
      </template>

      <h2 class="c-label">Another family</h2>
      <ul class="c-list">
        <li class="c-row">
          <Icon name="key" /><span class="me-auto">Join with a Join PIN</span
          ><Icon name="chevron-right" />
        </li>
        <li class="c-row">
          <Icon name="plus" /><span class="me-auto">Create a group</span
          ><Icon name="chevron-right" />
        </li>
      </ul>
    </section>

    <!-- ===== family Home (tidied) ===== -->
    <section v-else-if="current">
      <!-- Not linked: a set-up checklist where the hero would be. -->
      <div v-if="!current.linkedName" class="sl-panel mb-4">
        <h1 class="h3">Setting up {{ current.typedName }}’s family</h1>
        <ol class="c-steps">
          <li class="done"><Icon name="check-circle" /> Group created</li>
          <li :class="{ done: current.members.length > 1 }">
            <Icon :name="current.members.length > 1 ? 'check-circle' : 'user-plus'" />
            Invite family: Join PIN <code>{{ current.joinPin }}</code>
            <span class="small text-body-secondary">({{ current.members.length }} in so far)</span>
          </li>
          <li class="now">
            <Icon name="link" />
            <div>
              <strong>Link {{ current.typedName }}’s account</strong>
              <p class="small mb-2">
                On {{ current.typedName }}’s phone, Care+ shows a Senior-link PIN. Enter it here;
                showing it is their agreement. Steps, the watch and suggestions appear after.
              </p>
              <form
                class="d-flex gap-2"
                style="max-width: 20rem"
                @submit.prevent="emit('link', current.id)"
              >
                <input
                  v-model="pin"
                  class="form-control"
                  inputmode="numeric"
                  maxlength="6"
                  placeholder="6-digit PIN"
                />
                <button class="btn btn-primary" :disabled="pin.length < 6">Link</button>
              </form>
            </div>
          </li>
        </ol>
      </div>

      <template v-else>
        <h1 class="h3 mb-1">{{ seniorName(current) }}</h1>
        <p class="text-body-secondary">
          {{ current.steps?.toLocaleString() }} steps (usual
          {{ current.usualSteps?.toLocaleString() }}) ·
          {{ current.watch }}
        </p>
      </template>

      <!-- Single column, a "today" list rather than a dashboard grid. -->
      <ul class="c-list">
        <li class="c-row">
          <Icon name="calendar" /><span class="me-auto">{{ current.nextVisit }}</span>
        </li>
        <li class="c-row">
          <Icon name="checklist" /><span class="me-auto">2 tasks · Buy rice, Top up EZ-Link</span>
        </li>
        <li v-if="current.linkedName" class="c-row">
          <Icon name="sparkle" /><span class="me-auto"
            >Suggestion: tai chi at the AAC, Sat 10 am</span
          >
        </li>
        <li class="c-row">
          <Icon name="phone" /><span class="me-auto">Were you in touch today?</span
          ><button type="button" class="btn btn-sm btn-outline-primary">Check in</button>
        </li>
        <li class="c-row"><Icon name="sun" /><span class="me-auto">Partly cloudy, 31°</span></li>
      </ul>
      <p class="mt-3 small text-body-secondary">
        Family activity and the week of availability: Family page.
      </p>
    </section>
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

.c-head {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.6rem 0;
  border-bottom: 1px solid var(--sl-line);
}

.c-pill {
  gap: 0.15rem;
  margin: 0 auto;
  padding: 0.25rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
}

.c-pill button {
  padding: 0.4rem 1rem;
  border: 0;
  border-radius: 999px;
  background: none;
}

.c-pill button.on {
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}

.c-tabs {
  position: fixed;
  z-index: 20;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  border-top: 1px solid var(--sl-line);
  background: var(--bs-body-bg);
}

.c-tabs button {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  padding: 0.5rem 0;
  border: 0;
  background: none;
  font-size: 0.8rem;
}

.c-tabs button.on {
  color: var(--sl-jade-deep);
  font-weight: 700;
}

.c-rail {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding: 0.9rem 0;
  overflow-x: auto;
  border-bottom: 1px solid var(--sl-line);
}

.c-person {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: center;
  gap: 0.3rem;
  width: 5rem;
  border: 0;
  background: none;
}

.c-face {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 3.25rem;
  height: 3.25rem;
  border: 3px solid transparent;
  border-radius: 50%;
  background: var(--bs-tertiary-bg);
  font-weight: 700;
}

.c-face-sm {
  width: 2.25rem;
  height: 2.25rem;
  border-width: 2px;
  font-size: 0.8rem;
}

.c-person.on .c-face {
  border-color: var(--sl-jade);
  background: var(--sl-jade-soft);
}

.c-face.is-unlinked {
  border-color: var(--sl-sun);
  border-style: dashed;
}

.c-person.is-pending .c-face {
  border: 2px dashed var(--bs-secondary-color);
  background: none;
}

.c-plus {
  border: 2px dashed var(--sl-line);
  background: none;
}

.c-name {
  font-size: 0.8rem;
  line-height: 1.15;
  text-align: center;
}

.c-person.on .c-name {
  font-weight: 700;
}

.c-label {
  margin: 1.5rem 0 0.5rem;
  color: var(--bs-secondary-color);
  font-size: 0.8rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.c-list {
  margin: 0;
  padding: 0;
  overflow: hidden;
  list-style: none;
  border: 1px solid var(--sl-line);
  border-radius: 0.9rem;
}

.c-list > li + li {
  border-top: 1px solid var(--sl-line);
}

.c-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-height: 3.25rem;
  padding: 0.6rem 1rem;
  cursor: pointer;
  list-style: none;
}

.c-body {
  padding: 0 1rem 1rem 4rem;
}

.c-steps {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  margin: 1rem 0 0;
  padding: 0;
  list-style: none;
}

.c-steps li {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
}

.c-steps li.done {
  color: var(--sl-jade-deep);
}

.c-steps li.now {
  padding: 0.9rem;
  border-radius: 0.75rem;
  background: var(--sl-sun-soft);
}
</style>
