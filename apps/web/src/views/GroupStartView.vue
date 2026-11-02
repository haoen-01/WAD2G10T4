<script setup lang="ts">
import { computed, onMounted, ref, useId } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

import PinInput from '@/components/family/PinInput.vue';
import AuthShell from '@/components/ui/AuthShell.vue';
import Icon from '@/components/ui/Icon.vue';
import { useAction } from '@/composables/useAction';
import { loadMe, useMe } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { badgeText, groupUnreadLabel } from '@/lib/asks';
import { RELATIONSHIPS } from '@/lib/family';
import { createGroup, joinGroup } from '@/services/careApi';

/**
 * `/groups/start`: a family member who is not in a family group yet joins one (with a join PIN from
 * a member) or creates one (with the code on the senior's own screen). Two big buttons come first,
 * so there is only one form on screen at a time. The route guard sends a family member here until
 * they are an active member of a group.
 */
const router = useRouter();
const { me, currentGroup, pendingGroups, activeGroups, selectGroup } = useMe();
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

// Read afresh, so each group card's unread badge is current (the bell may have marked some read).
onMounted(() => void checking.run(async () => void (await loadMe(true))));

/** Open a group from its card: it becomes the current group, and Home shows it. */
async function openGroup(groupId: string) {
  selectGroup(groupId);
  await router.push('/');
}

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
    const group = await createGroup(createRelationship.value, { seniorPin: seniorPin.value });
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
  <AuthShell
    :title="hasGroup ? 'Add another family group' : 'Join your family'"
    lead="One family group looks after one senior. Pick one:"
    width="wide"
  >
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

    <!-- The groups this account is in, each with its unread notifications as a badge. -->
    <section v-if="activeGroups.length" class="mb-4" aria-labelledby="my-groups-title">
      <h2 id="my-groups-title" class="h5 mb-3">Your family groups</h2>
      <ul class="list-unstyled d-grid gap-2 mb-0">
        <li
          v-for="group in activeGroups"
          :key="group.group_id"
          class="sl-panel group-card d-flex align-items-center gap-3"
          data-testid="group-card"
        >
          <span class="choice-icon"><Icon name="users" /></span>
          <span class="me-auto">
            <strong class="d-block">{{ group.senior_name }}</strong>
            <span class="sl-note"
              >{{ group.member_count }} {{ group.member_count === 1 ? 'member' : 'members' }}</span
            >
          </span>
          <span v-if="group.unread_count > 0" class="group-unread" data-testid="group-unread"
            ><span aria-hidden="true">{{ badgeText(group.unread_count) }}</span
            ><span class="visually-hidden">{{ groupUnreadLabel(group.unread_count) }}</span></span
          >
          <button
            type="button"
            class="btn btn-outline-primary"
            :aria-label="`Open ${group.senior_name}’s family group`"
            @click="openGroup(group.group_id)"
          >
            Open
          </button>
        </li>
      </ul>
    </section>

    <!-- Step 1: two big, separate choices. -->
    <div v-if="choice === null" class="row g-3">
      <div class="col-sm-6">
        <button
          type="button"
          class="auth-choice sl-panel h-100"
          data-testid="choose-join"
          @click="choose('join')"
        >
          <span class="choice-icon"><Icon name="users" /></span>
          <span>
            <span class="choice-title">Join a group</span>
            <span class="choice-text">Your family already uses Care+.</span>
          </span>
        </button>
      </div>
      <div class="col-sm-6">
        <button
          type="button"
          class="auth-choice sl-panel h-100"
          data-testid="choose-create"
          @click="choose('create')"
        >
          <span class="choice-icon"><Icon name="user-plus" /></span>
          <span>
            <span class="choice-title">Create a group</span>
            <span class="choice-text">You are the first in your family.</span>
          </span>
        </button>
      </div>
    </div>

    <!-- Step 2a: join with a PIN from someone already in the group. -->
    <form
      v-else-if="choice === 'join'"
      class="sl-panel d-grid gap-3"
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
        <button type="button" class="btn btn-outline-primary btn-lg" @click="choose(null)">
          Back
        </button>
      </div>
    </form>

    <!-- Step 2b: create the group with the code on the senior's own screen. -->
    <form
      v-else
      class="sl-panel d-grid gap-3"
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
        <button type="button" class="btn btn-outline-primary btn-lg" @click="choose(null)">
          Back
        </button>
      </div>
    </form>

    <p v-if="hasGroup" class="mt-4 mb-0">
      <RouterLink to="/">Back to Home</RouterLink>
    </p>
    <p v-else-if="me" class="sl-note mt-4 mb-0">Signed in as {{ me.display_name }}.</p>
  </AuthShell>
</template>

<style scoped>
/* A group card: compact, so several fit above the join and create choices. */
.group-card {
  padding: 0.75rem 1rem;
}

/* The unread badge, in the bell's style (coral, white ring). Its label says the count in words. */
.group-unread {
  min-width: 1.5rem;
  height: 1.5rem;
  padding: 0 0.4rem;
  border-radius: 999px;
  background: var(--sl-coral);
  box-shadow: 0 0 0 2px var(--sl-surface);
  color: var(--sl-coral-on);
  font-size: 0.8rem;
  font-weight: 800;
  line-height: 1.5rem;
  text-align: center;
}

.steps {
  padding-left: 1.25rem;
}

.steps li + li {
  margin-top: 0.35rem;
}
</style>
