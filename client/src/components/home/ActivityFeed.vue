<script setup lang="ts">
import { computed, ref } from 'vue';
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
 *
 * `collapsible` (Home on a phone): the list starts folded, showing only the newest update, with a
 * Show button (a disclosure: `aria-expanded` on the button, `aria-controls` the list), so the page
 * stays short.
 */
const props = defineProps<{
  elder: string;
  members: readonly FamilyMember[];
  collapsible?: boolean;
}>();

const expanded = ref(false);
const folded = computed(() => props.collapsible && !expanded.value);

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
    <!-- Only once there is more than the one update the folded view already shows. -->
    <template v-if="collapsible && feed.loaded.value && lines.length > 1" #actions>
      <button
        type="button"
        class="btn btn-quiet feed-toggle"
        :aria-expanded="expanded"
        aria-controls="home-feed-list"
        data-testid="feed-toggle"
        @click="expanded = !expanded"
      >
        {{ expanded ? 'Hide' : `Show all (${lines.length})` }}
        <Icon :name="expanded ? 'chevron-up' : 'chevron-down'" />
      </button>
    </template>

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
      <p v-if="folded" class="feed-preview mb-0" data-testid="feed-preview">
        <strong>{{ lines[0].line.actor }}</strong> {{ lines[0].line.rest }}
        <span class="feed-meta-inline">
          · <time :datetime="lines[0].entry.at">{{ relativeTime(lines[0].entry.at, now) }}</time>
        </span>
      </p>

      <div v-show="!folded" id="home-feed-list">
        <StaggerList
          :items="lines"
          :item-key="(row: Row) => feed.renderKey(row.entry)"
          class="feed"
        >
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
      </div>
    </template>
  </BasePanel>
</template>

<style scoped>
.feed-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  flex: none;
}

.feed-preview {
  overflow-wrap: anywhere;
}

.feed-meta-inline {
  color: var(--sl-ink-soft);
  font-size: 0.9rem;
}

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
