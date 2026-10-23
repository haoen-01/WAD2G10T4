<script setup lang="ts">
import type { CareGroup, GroupMember, PinResponse } from '@silverloop/api-client';
import { computed, onMounted, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

import PinDisplay from '@/components/family/PinDisplay.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue';
import { useAction } from '@/composables/useAction';
import { loadMe, useMe } from '@/composables/useMe';
import { showToast } from '@/composables/useToast';
import { approveMember, declineMember, getGroup, getJoinPin } from '@/services/careApi';

/**
 * The family group as the API stores it: who is in it, who is waiting to be let in, and a join PIN
 * to invite someone. Anyone who joins with the PIN waits until a member here approves them.
 */
const { currentGroup } = useMe();
const { busy, error, run } = useAction();
const group = ref<CareGroup | null>(null);
const joinPin = ref<PinResponse | null>(null);
const loading = ref(true);

const active = computed(() => group.value?.members.filter((m) => m.status === 'active') ?? []);
const pending = computed(() => group.value?.members.filter((m) => m.status === 'pending') ?? []);

async function load() {
  await run(async () => {
    await loadMe();
    const id = currentGroup.value?.group_id;
    group.value = id ? await getGroup(id) : null;
  });
  loading.value = false;
}

function newPin() {
  const id = group.value?.group_id;
  if (!id) return;
  void run(async () => {
    joinPin.value = await getJoinPin(id);
  });
}

function decide(member: GroupMember, approve: boolean) {
  const id = group.value?.group_id;
  if (!id) return;
  void run(async () => {
    group.value = approve
      ? await approveMember(id, member.member_id)
      : await declineMember(id, member.member_id);
    showToast(
      approve
        ? `${member.display_name} is now in the group.`
        : `Request from ${member.display_name} turned down.`,
    );
  });
}

onMounted(load);
// Another senior picked in the navbar: show that family group.
watch(
  () => currentGroup.value?.group_id,
  (next, previous) => {
    if (previous !== undefined && next !== previous) {
      joinPin.value = null;
      void load();
    }
  },
);
</script>

<template>
  <BasePanel data-testid="group-panel">
    <template #title>
      <span class="d-inline-flex align-items-center gap-2"
        ><Icon name="users" />Your family group</span
      >
    </template>
    <LoadingSpinner v-if="loading" />
    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

    <template v-if="group">
      <p class="text-body-secondary mb-3">Caring for {{ group.senior_name }}.</p>

      <!-- Someone waiting is the one thing to act on, so it comes first and stands out. -->
      <section v-if="pending.length" class="waiting mb-3" aria-labelledby="pending-heading">
        <h3 id="pending-heading" class="h6 d-flex align-items-center gap-2 mb-1">
          <Icon name="clock" />Waiting to join
        </h3>
        <p class="sl-note mb-2">Only let in people you know.</p>
        <ul class="list-unstyled d-grid gap-2 mb-0">
          <li
            v-for="member in pending"
            :key="member.member_id"
            class="d-flex flex-wrap align-items-center gap-2"
            data-testid="pending-member"
          >
            <strong>{{ member.display_name }}</strong>
            <span class="text-body-secondary me-auto">{{ member.relationship }}</span>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="busy"
              @click="decide(member, true)"
            >
              <Icon name="check" class="me-1" />Let in
            </button>
            <button
              type="button"
              class="btn btn-outline-secondary btn-sm"
              :disabled="busy"
              @click="decide(member, false)"
            >
              Turn down
            </button>
          </li>
        </ul>
      </section>

      <div class="row g-3">
        <div class="col-md-6">
          <h3 class="h6 mb-2">Members ({{ active.length }})</h3>
          <ul class="list-unstyled d-flex flex-wrap gap-2 mb-0" aria-label="Members">
            <li v-for="member in active" :key="member.member_id" class="chip">
              <strong>{{ member.display_name }}</strong>
              <span class="text-body-secondary">{{ member.relationship }}</span>
              <span v-if="member.is_me" class="badge text-bg-light">You</span>
              <span v-if="member.role === 'owner'" class="visually-hidden"
                >, started the group</span
              >
            </li>
          </ul>
        </div>

        <div class="col-md-6">
          <h3 class="h6 d-flex align-items-center gap-2 mb-2">
            <Icon name="user-plus" />Invite family
          </h3>
          <p class="sl-note mb-2">Give them this PIN. You let them in after they enter it.</p>
          <PinDisplay
            v-if="joinPin"
            class="mb-2"
            :pin="joinPin.pin"
            :expires-at="joinPin.expires_at"
            testid="join-pin"
          />
          <button
            type="button"
            class="btn btn-outline-primary"
            :disabled="busy"
            data-testid="new-join-pin"
            @click="newPin"
          >
            {{ joinPin ? 'New PIN' : 'Show a join PIN' }}
          </button>
        </div>
      </div>

      <p class="sl-note mt-3 mb-0">
        Caring for someone else too?
        <RouterLink to="/groups/start">Join or create their group</RouterLink>.
      </p>
    </template>
  </BasePanel>
</template>

<style scoped>
.waiting {
  padding: 0.75rem 1rem;
  border: 2px solid var(--sl-sun);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-sun-soft);
}

.chip {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.75rem;
  border: 1px solid var(--sl-line);
  border-radius: 999px;
}
</style>
