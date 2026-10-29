<script setup lang="ts">
/**
 * PROTOTYPE A, throwaway. "Name chip in header": the switcher is a "Caring for {senior} ▾" chip
 * beside the brand (desktop and phone alike); the tab bar is unchanged. The groups page is a
 * stack of cards, one per group. The Link card takes the hero's place on Home.
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
const menuOpen = ref(false);
const pin = ref('');

function pick(id: string) {
  emit('select', id);
  menuOpen.value = false;
}

const TABS = [
  { label: 'Home', icon: 'home', screen: 'home' },
  { label: 'Walk', icon: 'walk', screen: null },
  { label: 'Calendar', icon: 'calendar', screen: null },
  { label: 'Family', icon: 'users', screen: null },
] as const;
</script>

<template>
  <div>
    <!-- ===== mock header ===== -->
    <header class="a-head">
      <span class="brand-mini">Care<b>+</b></span>
      <div class="position-relative">
        <button
          type="button"
          class="a-chip"
          :aria-expanded="menuOpen"
          @click="menuOpen = !menuOpen"
        >
          <span class="text-body-secondary d-none d-sm-inline">Caring for</span>
          <strong>{{ current ? seniorName(current) : '—' }}</strong>
          <span v-if="current && !current.linkedName" class="badge text-bg-warning"
            >not linked</span
          >
          <Icon name="chevron-down" />
        </button>
        <div v-if="menuOpen" class="a-menu">
          <p class="small text-body-secondary mb-1">Your family groups</p>
          <button
            v-for="g in active"
            :key="g.id"
            type="button"
            class="a-menu-item"
            @click="pick(g.id)"
          >
            <Icon :name="g.id === currentId ? 'check' : 'person'" />
            {{ seniorName(g) }}
            <span v-if="!g.linkedName" class="small text-body-secondary">(not linked)</span>
          </button>
          <div v-for="g in pending" :key="g.id" class="a-menu-item is-pending">
            <Icon name="clock" /> {{ seniorName(g) }}
            <span class="small">waiting to be let in</span>
          </div>
          <hr class="my-2" />
          <button
            type="button"
            class="a-menu-item"
            @click="
              menuOpen = false;
              emit('go', 'groups');
            "
          >
            <Icon name="users" /> All groups, Join PINs…
          </button>
        </div>
      </div>
      <nav class="a-pill d-none d-md-flex">
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
      <Icon name="sliders" class="ms-auto ms-md-0" />
    </header>
    <nav class="a-tabs d-md-none">
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

    <!-- ===== groups page ===== -->
    <section v-if="screen === 'groups'">
      <h1 class="h2 mb-1">Your family groups</h1>
      <p class="text-body-secondary">
        Pick whose care Home, Walk, Calendar and Family show. Share a group's Join PIN to invite
        family.
      </p>

      <div class="d-flex flex-column gap-3">
        <article
          v-for="g in groups"
          :key="g.id"
          class="sl-panel a-card"
          :class="{ 'is-current': g.id === currentId, 'is-pending': g.myStatus === 'pending' }"
        >
          <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
            <h2 class="h5 mb-0 me-auto">
              {{ seniorName(g) }}’s family
              <span v-if="g.id === currentId" class="badge text-bg-success ms-1">Showing</span>
              <span v-if="g.myStatus === 'pending'" class="badge text-bg-secondary ms-1"
                >Waiting</span
              >
              <span v-else-if="!g.linkedName" class="badge text-bg-warning ms-1"
                >{{ g.typedName }} not linked yet</span
              >
            </h2>
            <button
              v-if="g.myStatus === 'active' && g.id !== currentId"
              type="button"
              class="btn btn-outline-primary btn-sm"
              @click="
                emit('select', g.id);
                emit('go', 'home');
              "
            >
              Show on Home
            </button>
          </div>

          <template v-if="g.myStatus === 'pending'">
            <p class="mb-2">
              You asked to join. Someone in {{ seniorName(g) }}’s family needs to let you in.
            </p>
            <button type="button" class="btn btn-link btn-sm p-0">Cancel request</button>
          </template>

          <template v-else>
            <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
              <span
                v-for="m in g.members"
                :key="m.name"
                class="d-inline-flex align-items-center gap-1 me-2"
              >
                <MemberAvatar :name="m.name" :colour="m.colour" size="sm" />
                <span class="small">{{ m.name }} · {{ m.relationship }}</span>
              </span>
            </div>
            <p class="mb-0 d-flex align-items-center gap-2">
              <Icon name="key" /> Join PIN <code class="fs-5">{{ g.joinPin }}</code>
              <button type="button" class="btn btn-sm btn-outline-secondary">
                <Icon name="copy" /> Copy
              </button>
            </p>

            <!-- Link card, compact -->
            <div v-if="!g.linkedName" class="a-link mt-3">
              <p class="fw-semibold mb-1"><Icon name="link" /> Link {{ g.typedName }}’s account</p>
              <p class="small mb-2">
                Ask {{ g.typedName }} to open Care+ and show you their Senior-link PIN. Showing it
                is them agreeing to be linked; until then this group sees nothing about them.
              </p>
              <form class="d-flex gap-2" @submit.prevent="emit('link', g.id)">
                <input
                  v-model="pin"
                  class="form-control"
                  inputmode="numeric"
                  placeholder="6-digit PIN"
                  maxlength="6"
                />
                <button class="btn btn-primary" :disabled="pin.length < 6">Link</button>
              </form>
            </div>
          </template>
        </article>

        <article class="sl-panel a-card a-add">
          <h2 class="h6 mb-1"><Icon name="user-plus" /> Join or create another group</h2>
          <p class="small text-body-secondary mb-2">
            Join with a family member's Join PIN, or start a group and link the senior later.
          </p>
          <div class="d-flex gap-2">
            <button type="button" class="btn btn-outline-primary btn-sm">Join with a PIN</button>
            <button type="button" class="btn btn-outline-primary btn-sm">Create a group</button>
          </div>
        </article>
      </div>
    </section>

    <!-- ===== family Home (tidied) ===== -->
    <section v-else-if="current">
      <h1 class="h2 mb-1">Good afternoon, Wei Ling</h1>
      <p class="text-body-secondary">Caring for {{ seniorName(current) }}</p>

      <!-- Hero: steps + watch, or the Link card in its place. -->
      <div v-if="current.linkedName" class="sl-panel mb-4">
        <p class="mb-1 text-body-secondary">Steps today</p>
        <p class="display-6 mb-1">
          {{ current.steps?.toLocaleString() }}
          <span class="fs-6 text-body-secondary"
            >usual {{ current.usualSteps?.toLocaleString() }}</span
          >
        </p>
        <p class="small mb-0"><Icon name="watch" /> {{ current.watch }}</p>
      </div>
      <div v-else class="sl-panel a-link a-link-hero mb-4">
        <h2 class="h4"><Icon name="link" /> Link {{ current.typedName }}’s account</h2>
        <p>
          Steps, the watch and suggestions show here once {{ current.typedName }} is linked. Ask
          them to open Care+ on their phone and show you their Senior-link PIN.
        </p>
        <form
          class="d-flex gap-2"
          style="max-width: 22rem"
          @submit.prevent="emit('link', current.id)"
        >
          <input
            v-model="pin"
            class="form-control form-control-lg"
            inputmode="numeric"
            placeholder="6-digit PIN"
            maxlength="6"
          />
          <button class="btn btn-primary btn-lg" :disabled="pin.length < 6">Link</button>
        </form>
      </div>

      <div class="row g-4">
        <div class="col-12 col-lg-7 d-flex flex-column gap-4">
          <div class="sl-panel">
            <h2 class="sl-section-title">Today</h2>
            <p class="mb-0"><Icon name="calendar" /> Next: {{ current.nextVisit }}</p>
          </div>
          <div class="sl-panel">
            <h2 class="sl-section-title">Tasks</h2>
            <p class="mb-0 text-body-secondary">Buy rice · Top up EZ-Link</p>
          </div>
        </div>
        <div class="col-12 col-lg-5 d-flex flex-column gap-4">
          <div class="sl-panel">
            <h2 class="sl-section-title">Check in</h2>
            <button type="button" class="btn btn-outline-primary">I called today</button>
          </div>
          <div class="sl-panel">
            <h2 class="sl-section-title">Weather</h2>
            <p class="mb-0">Partly cloudy, 31°</p>
          </div>
        </div>
      </div>
      <p class="mt-4 small text-body-secondary">
        <Icon name="users" /> Family activity and who is free this week are on the Family page now.
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

.a-head {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin: 0 calc(-0.5 * var(--bs-gutter-x)) 1.5rem;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--sl-line);
}

.a-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  min-height: 2.75rem;
  padding: 0.3rem 0.9rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
  background: var(--bs-body-bg);
}

.a-menu {
  position: absolute;
  z-index: 30;
  top: calc(100% + 0.4rem);
  left: 0;
  min-width: 16rem;
  padding: 0.6rem;
  border: 1px solid var(--sl-line);
  border-radius: 0.75rem;
  background: var(--bs-body-bg);
  box-shadow: var(--sl-elev-2);
}

.a-menu-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  min-height: 2.75rem;
  padding: 0.3rem 0.5rem;
  border: 0;
  border-radius: 0.5rem;
  background: none;
  text-align: left;
}

.a-menu-item:hover {
  background: var(--bs-tertiary-bg);
}

.a-menu-item.is-pending {
  color: var(--bs-secondary-color);
}

.a-pill {
  gap: 0.15rem;
  margin: 0 auto;
  padding: 0.25rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
}

.a-pill button {
  padding: 0.4rem 1rem;
  border: 0;
  border-radius: 999px;
  background: none;
}

.a-pill button.on {
  background: var(--sl-jade);
  color: var(--sl-jade-on);
}

.a-tabs {
  position: fixed;
  z-index: 20;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  border-top: 1px solid var(--sl-line);
  background: var(--bs-body-bg);
}

.a-tabs button {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  padding: 0.5rem 0;
  border: 0;
  background: none;
  font-size: 0.8rem;
}

.a-tabs button.on {
  color: var(--sl-jade-deep);
  font-weight: 700;
}

.a-card.is-current {
  border-left: 4px solid var(--sl-jade);
}

.a-card.is-pending {
  border-style: dashed;
  opacity: 0.85;
}

.a-add {
  border-style: dashed;
}

.a-link {
  padding: 1rem;
  border-radius: 0.75rem;
  background: var(--sl-sun-soft, #fff6d6);
  color: var(--sl-ink);
}

.a-link-hero {
  padding: 1.5rem;
}
</style>
