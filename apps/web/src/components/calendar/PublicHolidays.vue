<script lang="ts">
import { defineComponent } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { formatIsoDay, formatMonthYear } from '@/lib/format-date';
import { holidaysByDay, holidaysInMonth, type PublicHoliday } from '@/lib/holidays';
import { getPublicHolidays } from '@/services/publicApis';

/**
 * Singapore's public holidays for the month on screen, fetched with Axios from Nager.Date. Each
 * year is fetched once and kept. After every load the component emits `loaded` with every holiday
 * it knows, keyed by date, so the parent can mark those days on the calendar grid.
 *
 * January and December grids also show a few days of the neighbouring year, so that year is
 * fetched too. Whether the list says "loading", "could not be loaded" or shows the holidays
 * depends only on the year on screen, so a slow answer for another year can never change it.
 */
export default defineComponent({
  name: 'PublicHolidays',
  components: { Icon },

  props: {
    year: { type: Number, required: true },
    /** 1 to 12 */
    month: { type: Number, required: true },
  },

  emits: {
    loaded: (byDay: Record<string, string>) => typeof byDay === 'object',
  },

  data() {
    return {
      byYear: {} as Record<number, PublicHoliday[]>,
      failedYears: [] as number[],
      pendingYears: [] as number[],
    };
  },

  computed: {
    status(): 'loading' | 'ready' | 'error' {
      if (this.byYear[this.year]) return 'ready';
      return this.failedYears.includes(this.year) ? 'error' : 'loading';
    },
    /** The years whose days appear on the grid for this month. */
    neededYears(): number[] {
      const years = [this.year];
      if (this.month === 1) years.push(this.year - 1);
      if (this.month === 12) years.push(this.year + 1);
      return years;
    },
    thisMonth(): PublicHoliday[] {
      return holidaysInMonth(this.byYear[this.year] ?? [], this.year, this.month);
    },
    monthName(): string {
      return formatMonthYear(this.year, this.month);
    },
  },

  watch: {
    // Runs once straight away, then again whenever the calendar moves to another month.
    neededYears: {
      handler(years: number[]) {
        for (const year of years) void this.load(year);
      },
      immediate: true,
    },
  },

  methods: {
    async load(year: number) {
      if (this.byYear[year] || this.pendingYears.includes(year)) return;
      this.failedYears = this.failedYears.filter((failed) => failed !== year);
      this.pendingYears = [...this.pendingYears, year];
      try {
        const holidays = await getPublicHolidays(year);
        this.byYear = { ...this.byYear, [year]: holidays };
        this.$emit('loaded', holidaysByDay(Object.values(this.byYear).flat()));
      } catch {
        this.failedYears = [...this.failedYears, year];
      } finally {
        this.pendingYears = this.pendingYears.filter((pending) => pending !== year);
      }
    },
    dayLabel(iso: string): string {
      return formatIsoDay(iso, { style: 'long' });
    },
  },
});
</script>

<template>
  <!-- Only when the month has holidays (or they failed to load): an empty box is just noise. -->
  <section
    v-if="status === 'error' || thisMonth.length"
    class="holidays"
    aria-labelledby="holidays-heading"
    data-testid="public-holidays"
  >
    <h2 id="holidays-heading" class="h6 d-flex align-items-center gap-2 mb-2">
      <Icon name="flag" />Public holidays
    </h2>

    <p v-if="status === 'loading'" class="text-body-secondary mb-0">Checking the holidays…</p>

    <p v-else-if="status === 'error'" class="text-body-secondary mb-0">
      The public holidays could not be loaded.
      <button type="button" class="btn btn-link p-0 align-baseline" @click="load(year)">
        Try again
      </button>
    </p>

    <p v-else-if="thisMonth.length === 0" class="text-body-secondary mb-0">
      No public holidays this month.
    </p>

    <ul v-else class="holiday-list">
      <li v-for="holiday in thisMonth" :key="holiday.date">
        <strong>{{ holiday.name }}</strong>
        <span class="text-body-secondary">{{ dayLabel(holiday.date) }}</span>
      </li>
    </ul>

    <p class="sl-note mt-2 mb-0">Source: Nager.Date</p>
  </section>
</template>

<style scoped>
.holidays {
  padding: 1rem 1.25rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius);
  background: var(--sl-surface);
}

.holiday-list {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.holiday-list li {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.75rem;
  padding-left: 0.75rem;
  border-left: 4px solid var(--sl-sun);
}
</style>
