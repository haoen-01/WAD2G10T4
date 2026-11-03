<script setup lang="ts">
import { computed, ref } from 'vue';
import { RouterLink } from 'vue-router';

import AvailabilityGrid from '@/components/family/AvailabilityGrid.vue';
import AvailabilityList from '@/components/family/AvailabilityList.vue';
import AvailabilityPainter from '@/components/family/AvailabilityPainter.vue';
import AvailabilityQuickPicks from '@/components/family/AvailabilityQuickPicks.vue';
import AvatarCluster from '@/components/family/AvatarCluster.vue';
import CareShare from '@/components/family/CareShare.vue';
import FamilyMemberCard from '@/components/family/FamilyMemberCard.vue';
import GroupPanel from '@/components/family/GroupPanel.vue';
import MemberAvatar from '@/components/family/MemberAvatar.vue';
import SeniorLocationCard from '@/components/family/SeniorLocationCard.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamily } from '@/composables/useFamily';
import { showToast } from '@/composables/useToast';
import { upcomingWithin } from '@/lib/coverage';
import type { AvailabilityEntry } from '@/lib/family';
import { describeWindow } from '@/lib/family';
import { formatIsoDay } from '@/lib/format-date';
import type { DayPartKey, SlotStatus } from '@/lib/planner';

const family = useFamily();
const { state, today, elderName, currentMember, appointments } = family;

function useAs(id: string) {
  family.setCurrentMember(id);
  const who = family.currentMember.value?.name;
  if (who) showToast(`Now viewing as ${who}.`);
}

// Windows only ("free on Friday afternoon"). An answer about one appointment is shown on that
// appointment in the calendar, next to the people it affects.
const windows = computed(() =>
  state.availability
    .filter((entry) => !entry.appointmentId && entry.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date) || a.start.localeCompare(b.start)),
);
const coming = computed(() => upcomingWithin(appointments, today, 13));

const helpingCount = (memberId: string) =>
  state.assignments.filter((assignment) => assignment.memberId === memberId).length;

// A painted day saves as soon as the drag ends; one toast however many days it touched.
let toastTimer: ReturnType<typeof setTimeout> | undefined;
function paint(day: string, slots: SlotStatus[]) {
  if (!family.paintDay(day, slots)) return;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => showToast('Saved.'), 50);
}

// The quick way: Morning, Afternoon, Evening or All day for a day. Saved at once.
function pick(day: string, part: DayPartKey) {
  if (!family.pickDayPart(day, part)) return;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => showToast('Saved.'), 50);
}

// The hour-by-hour painter is there for anyone who needs exact times, one click away.
const exactHours = ref(false);

function remove(entry: AvailabilityEntry) {
  family.removeAvailability(entry.id);
  showToast(`Removed ${formatIsoDay(entry.date)}, ${describeWindow(entry)}.`, {
    actionLabel: 'Undo',
    action: () =>
      family.addAvailability({
        date: entry.date,
        start: entry.start,
        end: entry.end,
        status: entry.status,
      }),
  });
}
</script>

<template>
  <div class="family-page">
    <header class="sl-page-head d-flex flex-wrap align-items-end gap-3">
      <div class="me-auto">
        <h1 class="mb-0">Family</h1>
        <p class="text-body-secondary mb-0">Caring for {{ elderName }}</p>
      </div>
      <AvatarCluster :members="state.members" :current-id="state.currentMemberId" />
      <RouterLink
        class="btn btn-outline-primary"
        :class="currentMember ? 'btn-sm' : 'btn-lg'"
        to="/groups/start"
        data-testid="to-groups"
      >
        <Icon name="user-plus" class="me-1" />Join or create a family group
      </RouterLink>
    </header>

    <!-- Sections have ids so links can jump to them:
         Group (#family-group) · Free times (#availability) · Sharing (#sharing). -->

    <p v-if="family.error.value" class="alert alert-danger" role="alert">
      {{ family.error.value }}
    </p>

    <!-- Not in a group yet: joining comes first. In one: painting your week does, so the group
         and its people (side by side) move below it. -->
    <div class="d-flex flex-column">
      <section
        id="family-group"
        class="row g-4 mb-5"
        :class="currentMember ? 'order-2' : 'order-1'"
        aria-label="Family group"
      >
        <div class="col-12 col-lg-7">
          <GroupPanel class="h-100" />
        </div>
        <div class="col-12 col-lg-5">
          <h2 id="members-heading" class="sl-section-title">Who helps</h2>
          <div class="row row-cols-1 row-cols-sm-2 row-cols-lg-1 g-2">
            <div v-for="member in state.members" :key="member.id" class="col">
              <FamilyMemberCard
                :member="member"
                :is-current="member.id === state.currentMemberId"
                :helping-count="helpingCount(member.id)"
                :can-switch="family.canViewAs"
                @use="useAs(member.id)"
              />
            </div>
          </div>
        </div>
      </section>

      <!-- Paint your week on the left; everyone's shared times on the right. -->
      <section id="availability" class="row g-4 mb-5 order-1" aria-label="Free times">
        <div class="col-12 col-xl-7">
          <h2 id="availability-heading" class="sl-section-title">When can you help?</h2>
          <div v-if="currentMember" class="sl-panel">
            <p class="d-flex align-items-center gap-2 mb-3">
              <MemberAvatar
                :name="currentMember.name"
                :colour="currentMember.colour"
                size="sm"
                current
              />
              <strong>{{ currentMember.name }}</strong>
            </p>
            <AvailabilityQuickPicks
              :today="today"
              :member-id="currentMember.id"
              :availability="state.availability"
              @pick="pick"
            />
            <button
              type="button"
              class="btn btn-link exact-toggle px-0"
              :aria-expanded="exactHours"
              :aria-controls="exactHours ? 'exact-hours' : undefined"
              data-testid="exact-hours-toggle"
              @click="exactHours = !exactHours"
            >
              <Icon
                name="chevron-right"
                class="exact-chevron me-1"
                :class="{ open: exactHours }"
              />Choose exact hours
            </button>
            <div v-if="exactHours" id="exact-hours" class="mt-2">
              <p class="sl-note">
                Paint the hours from 8 am to 9 pm. Times outside those hours, such as the early
                morning of an All day, stay as they are.
              </p>
              <AvailabilityPainter
                :today="today"
                :member-id="currentMember.id"
                :members="state.members"
                :availability="state.availability"
                @paint="paint"
              />
            </div>
          </div>
          <p v-else class="text-body-secondary">
            Only family members in the group can share when they are free.
          </p>
        </div>
        <div class="col-12 col-xl-5">
          <AvailabilityList
            :windows="windows"
            :members="state.members"
            :current-member-id="state.currentMemberId"
            :today="today"
            @remove="remove"
          />
        </div>
      </section>
    </div>

    <section v-if="state.members.length" id="sharing" class="mb-5" aria-labelledby="share-heading">
      <div class="row g-4">
        <!-- From xl the share of care sits beside the two-week grid; below that each takes the
             full width, so the grid's fourteen days fit without scrolling sideways. -->
        <div class="col-12 col-xl-5">
          <h2 id="share-heading" class="sl-section-title mb-1">Sharing the care</h2>
          <p class="text-body-secondary">Next 2 weeks · {{ coming.length }} visits</p>
          <div class="sl-panel">
            <CareShare
              :members="state.members"
              :assignments="state.assignments"
              :appointments="coming"
              :current-member-id="state.currentMemberId"
            />
          </div>
        </div>
        <div class="col-12 col-xl-7 d-none d-md-block">
          <h2 class="sl-section-title mb-1">The next two weeks</h2>
          <p class="text-body-secondary">Spot days when nobody is free.</p>
          <div class="sl-panel">
            <AvailabilityGrid
              :members="state.members"
              :availability="state.availability"
              :assignments="state.assignments"
              :appointments="appointments"
              :today="today"
              :current-member-id="state.currentMemberId"
            />
          </div>
        </div>
      </div>
    </section>

    <SeniorLocationCard :elder="elderName" />
  </div>
</template>

<style scoped>
.exact-toggle {
  display: inline-flex;
  align-items: center;
  margin-top: 0.75rem;
}

.exact-chevron {
  transition: transform var(--sl-dur-base) var(--sl-ease);
}

.exact-chevron.open {
  transform: rotate(90deg);
}
</style>
