<script lang="ts">
import { defineComponent } from 'vue';

import BasePanel from '@/components/ui/BasePanel.vue';
import Icon from '@/components/ui/Icon.vue';
import { isWet, plainForecast, weatherAdvice, type AreaForecast } from '@/lib/weather';
import { getTwoHourForecast } from '@/services/publicApis';

const AREA_KEY = 'silverloop.weather.area';
const DEFAULT_AREA = 'Toa Payoh';

/** The area picked last time in this browser, or the default. Storage can be blocked: never fail. */
function savedArea(): string {
  try {
    return localStorage.getItem(AREA_KEY) || DEFAULT_AREA;
  } catch {
    return DEFAULT_AREA;
  }
}

/**
 * The next two hours of weather where she lives, from NEA's public forecast on data.gov.sg,
 * fetched with Axios when the card appears. The area picker uses `v-model`; the choice is
 * remembered in this browser.
 */
export default defineComponent({
  name: 'WeatherCard',
  components: { BasePanel, Icon },

  data() {
    return {
      status: 'loading' as 'loading' | 'ready' | 'error',
      forecasts: [] as AreaForecast[],
      validFor: null as string | null,
      area: savedArea(),
    };
  },

  computed: {
    current(): AreaForecast | null {
      return this.forecasts.find((entry) => entry.area === this.area) ?? null;
    },
    wet(): boolean {
      return this.current ? isWet(this.current.forecast) : false;
    },
    summary(): string {
      return this.current ? plainForecast(this.current.forecast) : '';
    },
    advice(): string {
      return this.current ? weatherAdvice(this.current.forecast) : '';
    },
  },

  watch: {
    area(newArea: string) {
      try {
        localStorage.setItem(AREA_KEY, newArea);
      } catch {
        // Private browsing can refuse storage; the picker still works for this visit.
      }
    },
  },

  mounted() {
    void this.loadForecast();
  },

  methods: {
    async loadForecast() {
      this.status = 'loading';
      try {
        const summary = await getTwoHourForecast();
        this.forecasts = summary.forecasts;
        this.validFor = summary.validFor;
        // An area the API no longer lists falls back to the first one.
        if (!this.forecasts.some((entry) => entry.area === this.area)) {
          this.area = this.forecasts[0]?.area ?? DEFAULT_AREA;
        }
        this.status = 'ready';
      } catch {
        this.status = 'error';
      }
    },
  },
});
</script>

<template>
  <BasePanel
    title="Weather nearby"
    heading-class="h4 mb-0"
    class="weather"
    :class="{ wet: status === 'ready' && wet }"
    data-testid="weather-card"
  >
    <template #actions>
      <button
        type="button"
        class="btn btn-quiet btn-sm"
        :disabled="status === 'loading'"
        @click="loadForecast"
      >
        <Icon name="refresh" class="me-1" />Refresh
      </button>
    </template>

    <div v-if="status === 'loading'" class="placeholder-glow" aria-hidden="true">
      <span class="placeholder col-8 mb-2"></span>
      <span class="placeholder col-12"></span>
    </div>

    <p v-else-if="status === 'error'" class="text-body-secondary mb-0" role="status">
      The weather forecast could not be loaded right now.
      <button type="button" class="btn btn-link p-0 align-baseline" @click="loadForecast">
        Try again
      </button>
    </p>

    <template v-else>
      <label for="weather-area" class="form-label small fw-bold mb-1">Area</label>
      <select id="weather-area" v-model="area" class="form-select mb-3">
        <option v-for="entry in forecasts" :key="entry.area" :value="entry.area">
          {{ entry.area }}
        </option>
      </select>

      <div v-if="current" class="d-flex align-items-start gap-3" aria-live="polite">
        <span class="weather-icon" aria-hidden="true">
          <Icon :name="wet ? 'umbrella' : 'sun'" />
        </span>
        <div>
          <p class="weather-now mb-1" data-testid="weather-forecast">{{ summary }}</p>
          <p class="mb-0">{{ advice }}</p>
        </div>
      </div>

      <p class="sl-note mt-3 mb-0">
        2-hour forecast<template v-if="validFor"> for {{ validFor }}</template
        >, from NEA on data.gov.sg.
      </p>
    </template>
  </BasePanel>
</template>

<style scoped>
.weather.wet {
  border-color: var(--sl-coral-soft);
}

.weather-icon {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 3rem;
  height: 3rem;
  border-radius: 50%;
  background: var(--sl-sun-soft);
}

.wet .weather-icon {
  background: var(--sl-mist);
}

.weather-icon .sl-icon {
  width: 1.6rem;
  height: 1.6rem;
}

.weather-now {
  font-size: 1.3rem;
  font-weight: 700;
}
</style>
