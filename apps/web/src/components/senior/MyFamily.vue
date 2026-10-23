<script setup lang="ts">
import { computed } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamily } from '@/composables/useFamily';
import type { FamilyMember } from '@/lib/family';

/**
 * "My family": who is in the senior's group, small cards with a picture, a name and how they are
 * related. Read only; the family's own screens change the group.
 *
 * Built for a list of groups, but the API gives a senior one group (`care_groups.person_id` is
 * unique) and no group name, photo or caregiver flag yet, so today there is always one group and
 * neither the photo nor the "Caregiver" label shows. Nothing here is made up to fill them in.
 */
interface MemberView extends FamilyMember {
  /** Not in the API yet. */
  photoUrl?: string;
  /** Not in the API yet: a professional or external carer rather than family. */
  caregiver?: boolean;
}

interface GroupView {
  id: string;
  /** Not in the API yet; only shown when there is more than one group. */
  name: string | null;
  members: MemberView[];
}

const { state, groupId, loading, loaded, error } = useFamily();

const groups = computed<GroupView[]>(() =>
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
      No family linked yet.
    </p>
    <template v-else>
      <div v-for="group in groups" :key="group.id" class="mb-3 last-mb-0">
        <h3 v-if="showGroupNames" class="h6 fw-bold mb-2">{{ group.name ?? 'Family group' }}</h3>
        <ul
          class="list-unstyled row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-2 row-cols-xxl-3 g-2 mb-0"
          data-testid="my-family"
        >
          <li v-for="member in group.members" :key="member.id" class="col">
            <div
              class="d-flex flex-column align-items-center text-center gap-1 border rounded-3 p-2 h-100"
            >
              <img
                v-if="member.photoUrl"
                :src="member.photoUrl"
                :alt="member.name"
                class="member-photo rounded-circle"
              />
              <span v-else role="img" :aria-label="member.name">
                <MemberAvatar :name="member.name" :colour="member.colour" />
              </span>
              <span class="fw-bold text-break">{{ member.name }}</span>
              <span v-if="member.relationship" class="small text-break">
                {{ member.relationship }}
              </span>
              <span
                v-if="member.caregiver"
                class="badge rounded-pill border text-body d-inline-flex align-items-center gap-1"
              >
                <Icon name="shield-check" />Caregiver
              </span>
            </div>
          </li>
        </ul>
      </div>
    </template>
  </BasePanel>
</template>

<style scoped>
.member-photo {
  width: 2.5rem;
  height: 2.5rem;
  object-fit: cover;
}

.last-mb-0:last-child {
  margin-bottom: 0 !important;
}
</style>
