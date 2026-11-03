<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import { RouterLink } from 'vue-router';

import MemberAvatar from '@/components/family/MemberAvatar.vue';
import ErrorAlert from '@/components/ErrorAlert.vue';
import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { useFamilyActivity } from '@/composables/useFamilyActivity';
import { useNow } from '@/composables/useNow';
import { feedLine, feedLink, relativeTime } from '@/lib/family-feed';
import { capRows } from '@/lib/home';
import type { FamilyMember } from '@/lib/family';

/**
 * What the family has been doing, newest first: who took a visit, who called, who added a note.
 * It stays live while Home is open (see `useFamilyActivity`). Entries are facts members chose to
 * share with the group; nothing here is a prompt or a warning. Home's "Recently": five rows, then
 * "See all updates" opens the rest in place (there is no separate feed page). Seeded entries are
 * sample data: the screen's one "Sample data" notice says so, and each one says it to a screen
 * reader too.
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

const listId = useId();
const expanded = ref(false);
const rows = computed(() => (expanded.value ? lines.value : capRows(lines.value).shown));
const hidden = computed(() => capRows(lines.value).hidden);
</script>

<template>
  <BasePanel id="home-feed" title="Recently" heading-class="sl-section-title mb-1">
    <p class="sl-note mb-3">What the family has done for {{ elder }}, newest first.</p>

    <ErrorAlert
      v-if="feed.error.value && !feed.loaded.value"
      :message="feed.error.value"
      @retry="feed.refresh()"
    />

    <div v-else-if="!feed.loaded.value" role="status" data-testid="feed-loading">
      <span class="visually-hidden">Loading family updates…</span>
      <div v-for="n in 3" :key="n" class="feed-row" aria-hidden="true">
        <span class="sl-skeleton sk-avatar"></span>
        <div class="flex-grow-1">
          <span class="sl-skeleton sk-text"></span>
          <span class="sl-skeleton sk-meta"></span>
        </div>
      </div>
    </div>

    <div v-else-if="lines.length === 0" class="feed-empty">
      <Icon name="users" class="feed-empty-icon" />
      <p class="mb-0">
        Nothing yet. When someone takes a visit, adds a note or tells the family they were in touch,
        it shows here.
      </p>
    </div>

    <template v-else>
      <!-- No entrance: on Home only the hero arrives with motion; the feed is simply there. -->
      <ul :id="listId" class="feed list-unstyled mb-0">
        <li v-for="item in rows" :key="feed.renderKey(item.entry)">
          <div
            class="feed-row"
            :data-sample="item.entry.origin === 'demo_seed' ? 'true' : undefined"
          >
            <MemberAvatar
              :name="item.entry.actor_name"
              :colour="item.colour"
              :current="item.entry.is_me"
            />
            <div class="feed-body">
              <p class="feed-text">
                <strong>{{ item.line.actor }}</strong> {{ item.line.rest }}
                <span v-if="item.entry.origin === 'demo_seed'" class="visually-hidden">
                  (sample update)</span
                >
              </p>
              <p v-if="item.line.note" class="feed-quote">“{{ item.line.note }}”</p>
              <p class="feed-meta">
                <Icon :name="item.line.icon" class="feed-icon" />
                <time :datetime="item.entry.at">{{ relativeTime(item.entry.at, now) }}</time>
                <RouterLink v-if="item.link" :to="item.link" class="feed-link">
                  View on calendar
                </RouterLink>
              </p>
            </div>
          </div>
        </li>
      </ul>

      <button
        v-if="hidden > 0 || expanded"
        type="button"
        class="btn btn-link see-all"
        :aria-expanded="expanded"
        :aria-controls="listId"
        data-testid="feed-see-all"
        @click="expanded = !expanded"
      >
        {{ expanded ? 'Show fewer' : `See all updates (${lines.length})` }}
      </button>

      <div v-if="expanded && feed.nextBefore.value" class="mt-2">
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
          {{ feed.loadingMore.value ? 'Loading…' : 'Show older updates' }}
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
.feed-empty {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem;
  border-radius: var(--sl-radius-sm);
  background: var(--bs-tertiary-bg);
  color: var(--sl-ink-soft);
}

.feed-empty-icon {
  margin-top: 0.15rem;
  color: var(--sl-jade);
}

.see-all {
  margin-top: 0.25rem;
  padding-inline: 0;
}

.sk-avatar {
  flex: none;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 50%;
}

.sk-text {
  width: 70%;
  height: 1.1rem;
  margin: 0.2rem 0 0.5rem;
}

.sk-meta {
  width: 35%;
  height: 0.9rem;
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
