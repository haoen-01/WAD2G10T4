<script setup lang="ts">
import { computed, onMounted, ref, useId } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

import PinInput from '@/components/family/PinInput.vue';
import Icon from '@/components/ui/Icon.vue';
import { useAction } from '@/composables/useAction';
import { loadMe, useMe } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { RELATIONSHIPS } from '@/lib/family';
import { createGroup, joinGroup } from '@/services/careApi';

/**
 * `/groups/start`: a family member who is not in a family group yet joins one (with a join PIN from
 * a member) or creates one (with the code on the senior's own screen). Two big buttons come first,
 * so there is only one form on screen at a time. The route guard sends a family member here until
 * they are an active member of a group.
 */
const router = useRouter();
const { me, currentGroup, pendingGroups } = useMe();
const join = useAction();
const create = useAction();
const checking = useAction();

/** Which form is open: none until one of the two big buttons is pressed. */
const choice = ref<'join' | 'create' | null>(null);

const joinPin = ref('');
const joinRelationship = ref<string>(RELATIONSHIPS[0]);
const seniorPin = ref('');
const createRelationship = ref<string>(RELATIONSHIPS[0]);
const joinRelId = useId();
const createRelId = useId();

const hasGroup = computed(() => currentGroup.value !== null);

onMounted(() => void checking.run(async () => void (await loadMe())));

function choose(next: 'join' | 'create' | null) {
  choice.value = next;
  join.error.value = null;
  create.error.value = null;
}

function submitJoin() {
  void join.run(async () => {
    const group = await joinGroup(joinPin.value, joinRelationship.value);
    joinPin.value = '';
    choice.value = null;
    await loadMe(true);
    showToast(
      `Asked to join ${group.senior_name}’s family. Someone in the group needs to let you in.`,
    );
  });
}

function submitCreate() {
  void create.run(async () => {
    const group = await createGroup(seniorPin.value, createRelationship.value);
    await loadMe(true);
    showToast(`${group.senior_name}’s family group is ready.`);
    await router.replace('/family');
  });
}

/** Waiting for approval: look again, and go in once someone has let them in. */
function checkAgain() {
  void checking.run(async () => {
    await loadMe(true);
    if (currentGroup.value) await router.replace('/');
  });
}
</script>

<template>
  <div class="group-start">
    <header class="sl-page-head">
      <h1>{{ hasGroup ? 'Add another family group' : 'Join your family' }}</h1>
      <p class="sl-lede mb-0">One family group looks after one senior. Pick one:</p>
    </header>

    <div v-if="checking.error.value" class="alert alert-danger" role="alert">
      {{ checking.error.value }}
    </div>

    <section
      v-for="group in pendingGroups"
      :key="group.group_id"
      class="alert alert-info d-flex flex-wrap align-items-center gap-3"
      data-testid="waiting-approval"
    >
      <Icon name="clock" />
      <span class="me-auto">
        Waiting for <strong>{{ group.senior_name }}</strong
        >’s family to let you in.
      </span>
      <button
        type="button"
        class="btn btn-outline-primary"
        :disabled="checking.busy.value"
        @click="checkAgain"
      >
        Check again
      </button>
    </section>

    <!-- Step 1: two big, separate choices. -->
    <div v-if="choice === null" class="row g-3">
      <div class="col-sm-6">
        <button
          type="button"
          class="choice sl-panel w-100 h-100"
          data-testid="choose-join"
          @click="choose('join')"
        >
          <span class="choice-icon choice-join"><Icon name="users" /></span>
          <span class="choice-title">Join a group</span>
          <span class="choice-text">Your family already uses Care+.</span>
        </button>
      </div>
      <div class="col-sm-6">
        <button
          type="button"
          class="choice sl-panel w-100 h-100"
          data-testid="choose-create"
          @click="choose('create')"
        >
          <span class="choice-icon choice-create"><Icon name="user-plus" /></span>
          <span class="choice-title">Create a group</span>
          <span class="choice-text">You are the first in your family.</span>
        </button>
      </div>
    </div>

    <!-- Step 2a: join with a PIN from someone already in the group. -->
    <form
      v-else-if="choice === 'join'"
      class="sl-panel step d-grid gap-3"
      aria-labelledby="join-title"
      @submit.prevent="submitJoin"
    >
      <h2 id="join-title" class="h4 mb-0 d-flex align-items-center gap-2">
        <Icon name="users" />Join a group
      </h2>
      <p class="mb-0">Ask someone in the group for the join PIN. It is on their Family page.</p>
      <PinInput v-model="joinPin" label="Join PIN" testid="join-pin-input" />
      <div>
        <label :for="joinRelId" class="form-label">You are their</label>
        <select :id="joinRelId" v-model="joinRelationship" class="form-select form-select-lg">
          <option v-for="option in RELATIONSHIPS" :key="option">{{ option }}</option>
        </select>
      </div>
      <div v-if="join.error.value" class="alert alert-danger mb-0" role="alert">
        {{ join.error.value }}
      </div>
      <div class="d-flex flex-wrap gap-2">
        <button
          type="submit"
          class="btn btn-primary btn-lg"
          :disabled="join.busy.value || joinPin.length !== 6"
        >
          Ask to join
        </button>
        <button type="button" class="btn btn-outline-secondary btn-lg" @click="choose(null)">
          Back
        </button>
      </div>
    </form>

    <!-- Step 2b: create the group with the code on the senior's own screen. -->
    <form
      v-else
      class="sl-panel step d-grid gap-3"
      aria-labelledby="create-title"
      @submit.prevent="submitCreate"
    >
      <h2 id="create-title" class="h4 mb-0 d-flex align-items-center gap-2">
        <Icon name="user-plus" />Create a group
      </h2>
      <ol class="steps mb-0">
        <li>The senior signs in to Care+ on their own phone.</li>
        <li>They tap <strong>Add a family member</strong>, then show the code.</li>
        <li>Type the code here. It works once, for 10 minutes.</li>
      </ol>
      <PinInput v-model="seniorPin" label="The senior’s code" testid="senior-pin-input" />
      <div>
        <label :for="createRelId" class="form-label">You are their</label>
        <select :id="createRelId" v-model="createRelationship" class="form-select form-select-lg">
          <option v-for="option in RELATIONSHIPS" :key="option">{{ option }}</option>
        </select>
      </div>
      <div v-if="create.error.value" class="alert alert-danger mb-0" role="alert">
        {{ create.error.value }}
      </div>
      <div class="d-flex flex-wrap gap-2">
        <button
          type="submit"
          class="btn btn-primary btn-lg"
          :disabled="create.busy.value || seniorPin.length !== 6"
        >
          Start the group
        </button>
        <button type="button" class="btn btn-outline-secondary btn-lg" @click="choose(null)">
          Back
        </button>
      </div>
    </form>

    <p v-if="hasGroup" class="mt-4 mb-0">
      <RouterLink to="/">Back to Home</RouterLink>
    </p>
    <p v-else-if="me" class="sl-note mt-4 mb-0">Signed in as {{ me.display_name }}.</p>
  </div>
</template>

<style scoped>
.group-start {
  max-width: 48rem;
}

.choice {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  border: 2px solid var(--sl-line);
  color: var(--sl-ink);
  text-align: center;
  transition:
    border-color 0.15s ease,
    transform 0.15s var(--sl-ease);
}

.choice:hover {
  border-color: var(--sl-jade);
  transform: translateY(-2px);
}

.choice:focus-visible {
  outline: 3px solid var(--sl-jade);
  outline-offset: 2px;
}

.choice-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 3.5rem;
  height: 3.5rem;
  border-radius: 50%;
  font-size: 1.6rem;
}

.choice-join {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.choice-create {
  background: var(--sl-sun-soft);
  color: var(--sl-ink);
}

.choice-title {
  font-size: 1.35rem;
  font-weight: 800;
}

.choice-text {
  color: var(--sl-ink-soft);
}

.step {
  max-width: 34rem;
}

.steps {
  padding-left: 1.25rem;
}

.steps li + li {
  margin-top: 0.35rem;
}
</style>
