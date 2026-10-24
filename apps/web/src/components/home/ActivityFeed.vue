<script setup lang="ts">
import { computed } from 'vue';
import { RouterLink } from 'vue-router';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import ErrorAlert from '@/components/ErrorAlert.vue';
import StaggerList from '@/components/motion/StaggerList.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamilyActivity } from '@/composables/useFamilyActivity';
import { useNow } from '@/composables/useNow';
import { feedLine, feedLink, relativeTime } from '@/lib/family-feed';
import type { FamilyMember } from '@/lib/family';

/**
 * What the family has been doing, newest first: who took a visit, who called, who added a note.
 * It stays live while Home is open (see `useFamilyActivity`). Entries are facts members chose to
 * share with the group; nothing here is a prompt or a warning.
 */
const props = defineProps<{ elder: string; members: readonly FamilyMember[] }>();

const feed = useFamilyActivity();
const now = useNow();

const lines = computed(() =>
  feed.entries.value.map((entry) => ({
    entry,
    line: feedLine(entry, { elder: props.elder }),
    link: feedLink(entry),
    colour: props.members.find((member) => member.id === entry.actor_member_id)?.colour ?? 0,
  })),
);
type Row = (typeof lines.value)[number];
</script>

<template>
  <BasePanel
    id="home-feed"
    title="Family updates"
    heading-class="h4 d-flex align-items-center gap-2"
  >
    <template #title><Icon name="users" />Family updates</template>

    <ErrorAlert
      v-if="feed.error.value && !feed.loaded.value"
      :message="feed.error.value"
      @retry="feed.refresh()"
    />

    <div v-else-if="!feed.loaded.value" class="py-4 text-center" role="status">
      <div class="spinner-border spinner-border-sm" aria-hidden="true"></div>
      <span class="visually-hidden">Loading family updates…</span>
    </div>

    <p v-else-if="lines.length === 0" class="sl-note mb-0">
      Nothing yet. When someone takes a visit, adds a note or checks in, it shows here.
    </p>

    <template v-else>
      <StaggerList :items="lines" :item-key="(row: Row) => feed.renderKey(row.entry)" class="feed">
        <template #item="{ item }">
          <div class="feed-row">
            <MemberAvatar
              :name="item.entry.actor_name"
              :colour="item.colour"
              :current="item.entry.is_me"
            />
            <div class="feed-body">
              <p class="feed-text">
                <strong>{{ item.line.actor }}</strong> {{ item.line.rest }}
              </p>
              <p v-if="item.line.note" class="feed-quote">“{{ item.line.note }}”</p>
              <p class="feed-meta">
                <Icon :name="item.line.icon" class="feed-icon" />
                <time :datetime="item.entry.at">{{ relativeTime(item.entry.at, now) }}</time>
                <span v-if="item.entry.origin === 'demo_seed'" class="badge text-bg-secondary">
                  Sample
                </span>
                <RouterLink v-if="item.link" :to="item.link" class="feed-link">
                  View on calendar
                </RouterLink>
              </p>
            </div>
          </div>
        </template>
      </StaggerList>

      <div v-if="feed.nextBefore.value" class="mt-3 text-center">
        <button
          type="button"
          class="btn btn-outline-primary"
          :disabled="feed.loadingMore.value"
          @click="feed.showMore()"
        >
          <span
            v-if="feed.loadingMore.value"
            class="spinner-border spinner-border-sm me-2"
            aria-hidden="true"
          ></span>
          {{ feed.loadingMore.value ? 'Loading…' : 'Show more' }}
        </button>
      </div>
      <ErrorAlert
        v-if="feed.error.value"
        class="mt-3"
        :message="feed.error.value"
        @retry="feed.showMore()"
      />
    </template>
  </BasePanel>
</template>

<style scoped>
.feed-row {
  display: flex;
  gap: 0.85rem;
  padding: 0.85rem 0;
  border-top: 1px solid var(--sl-line);
}

li:first-child > .feed-row {
  border-top: 0;
  padding-top: 0.25rem;
}

.feed-body {
  min-width: 0;
}

.feed-text {
  margin: 0;
  overflow-wrap: anywhere;
}

.feed-quote {
  margin: 0.15rem 0 0;
  color: var(--sl-ink-soft);
  font-style: italic;
  overflow-wrap: anywhere;
}

.feed-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0.25rem 0 0;
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
}

.feed-icon {
  color: var(--sl-jade);
}

/* A 44px tap target without a taller row: the padding is cancelled by the negative margin. */
.feed-link {
  display: inline-flex;
  align-items: center;
  min-height: 2.75rem;
  margin-block: -0.75rem;
  padding-inline: 0.25rem;
  font-weight: 600;
}
</style>
