<script lang="ts">
import { defineComponent, type PropType } from 'vue';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import type { FamilyMember } from '@/lib/family';

/**
 * "Viewing as": which family member is using the calendar, with their avatar. Used with
 * `v-model`, which holds that member's id:
 *
 *   <ViewingAsPicker v-model="viewerId" :members="members" />
 */
export default defineComponent({
  name: 'ViewingAsPicker',
  components: { MemberAvatar },

  props: {
    members: { type: Array as PropType<FamilyMember[]>, required: true },
    modelValue: { type: String as PropType<string | null>, default: null },
  },

  emits: {
    'update:modelValue': (id: string) => typeof id === 'string',
  },

  computed: {
    current(): FamilyMember | null {
      return this.members.find((member) => member.id === this.modelValue) ?? null;
    },
  },

  methods: {
    onChange(event: Event) {
      this.$emit('update:modelValue', (event.target as HTMLSelectElement).value);
    },
  },
});
</script>

<template>
  <!-- One slim line: avatar, "Viewing as", and the name to pick. -->
  <div class="viewer">
    <MemberAvatar v-if="current" :name="current.name" :colour="current.colour" size="sm" current />
    <label for="viewer" class="viewer-label">Viewing as</label>
    <select
      id="viewer"
      class="form-select form-select-sm viewer-select"
      :value="modelValue ?? ''"
      @change="onChange"
    >
      <option v-for="member in members" :key="member.id" :value="member.id">
        {{ member.name }}
      </option>
    </select>
  </div>
</template>

<style scoped>
/* On a narrow phone at a large text size the name to pick goes under "Viewing as", never off the
   side of the page. */
.viewer {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  max-width: 100%;
}

.viewer-label {
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
  font-weight: 600;
  white-space: nowrap;
}

.viewer-select {
  width: auto;
  min-width: min(7rem, 100%);
  max-width: 100%;
  font-weight: 600;
}
</style>
