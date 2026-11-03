<script setup lang="ts">
import { computed } from 'vue';
import MemberAvatar from '@/components/family/MemberAvatar.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamily } from '@/composables/useFamily';
const { state, groupId, loading, loaded, error } = useFamily();
const groups = computed(() =>
  state.members.length === 0
    ? []
    : [{ id: groupId.value ?? 'family', name: null, members: state.members }],
);
const showGroupNames = computed(() => groups.value.length > 1);
// Only the first read shows "Loading": a later re-read keeps the list on screen.
const firstLoad = computed(() => loading.value && !loaded.value);
</script>

<template>
  <BasePanel id="my-family" heading-class="h3 d-flex align-items-center gap-2">
    <template #title><Icon name="users" />My family</template>
    <p class="fs-5 mb-3">Your family can help you.</p>

    <p v-if="firstLoad" class="fs-5 mb-0" role="status">Loading your family…</p>
    <p v-else-if="error && !loaded" class="fs-5 mb-0">Your family can’t be shown right now.</p>
    <p v-else-if="groups.length === 0" class="fs-5 mb-0" data-testid="my-family-empty">
      No family linked yet. Show your family the PIN below so they can link to you.
    </p>
    <template v-else>
      <div v-for="group in groups" :key="group.id" class="mb-3 last-mb-0">
        <h3 v-if="showGroupNames" class="h6 fw-bold mb-2">{{ group.name ?? 'Family group' }}</h3>
        <ul
          class="list-unstyled row row-cols-2 row-cols-lg-3 row-cols-xl-4 g-2 mb-0"
          data-testid="my-family"
        >
          <li v-for="member in group.members" :key="member.id" class="col">
            <div
              class="d-flex flex-column align-items-center text-center gap-1 border rounded-3 p-2 h-100"
            >
              <span role="img" :aria-label="member.name">
                <MemberAvatar :name="member.name" :colour="member.colour" />
              </span>
              <span class="fw-bold text-break">{{ member.name }}</span>
              <span v-if="member.relationship" class="small text-break">
                {{ member.relationship }}
              </span>
            </div>
          </li>
        </ul>
      </div>
    </template>
    <slot />
  </BasePanel>
</template>

<style scoped>
.last-mb-0:last-child {
  margin-bottom: 0 !important;
}
</style>
