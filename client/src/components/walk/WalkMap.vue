<script setup lang="ts">
import type { GeoJSONSource, Map as MapLibreMap, Marker } from 'maplibre-gl';
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';

import Icon from '@/components/ui/Icon.vue';
import { useDisplay } from '@/composables/useDisplay';
import type { DemoRoute } from '@/lib/demo-walk';
import { circleRing, type LngLat } from '@/lib/geo';
import {
  ensure3dBuildings,
  fetchStyle,
  LOOKS,
  SKETCH_LABELS,
  sketchStyle,
  type MapLook,
  type StyleSpecification,
} from '@/lib/map-style';
import type { WalkFix } from '@/lib/walk';

/**
 * The live walk on a map you can explore: drag to move, scroll or pinch to zoom, right-drag or
 * two fingers to turn and tilt, or use the keyboard once the map has focus (arrow keys move,
 * + and − zoom, Shift + arrows turn and tilt). Buttons switch 2D / 3D, change the map's look,
 * follow her, and point the map north again.
 *
 * MapLibre (and its map pictures) load only when this map is first shown. The map is a picture of
 * what the page already says in words, so it is hidden from screen readers; the Walk page gives the
 * same facts as text.
 */
const props = defineProps<{
  route: DemoRoute;
  /** The readings to draw as the walked trail (up to now, or up to the replay time). */
  trail: readonly WalkFix[];
  /** Where to put her marker: the latest reading, or the one at the replay time. */
  position: WalkFix | null;
  /** False while replaying: the marker is drawn faded and does not pulse. */
  live: boolean;
  seniorName: string;
}>();

const follow = defineModel<boolean>('follow', { required: true });
const threeD = defineModel<boolean>('threeD', { required: true });
const look = defineModel<MapLook>('look', { required: true });

const { theme } = useDisplay();

const container = ref<HTMLElement | null>(null);
const map = shallowRef<MapLibreMap | null>(null);
const ready = ref(false);
const failed = ref<string | null>(null);
const notice = ref<string | null>(null);
const bearing = ref(0);
const layersOpen = ref(false);
const layersBox = ref<HTMLElement | null>(null);

function closeLayers() {
  layersOpen.value = false;
}

// A tap or click anywhere else closes the map-look menu.
function onPointerDown(event: PointerEvent) {
  if (layersOpen.value && !layersBox.value?.contains(event.target as Node)) closeLayers();
}

let noticeTimer: number | null = null;
function showNotice(text: string) {
  notice.value = text;
  if (noticeTimer !== null) window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => (notice.value = null), 10_000);
}

let MarkerClass: typeof Marker | null = null;
let meMarker: Marker | null = null;
let homeMarker: Marker | null = null;
let labelMarkers: Marker[] = [];
let extrusionLayers: string[] = [];

const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const css = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#0b684f';

const centreOf = (fix: WalkFix | null): LngLat =>
  fix ? [fix.lng, fix.lat] : [props.route.home.lng, props.route.home.lat];

// ---- Map styles ----

// Only the latest change of look (or theme) wins, however long the slower one takes to download.
let styleGeneration = 0;

async function styleFor(next: MapLook, generation = styleGeneration): Promise<StyleSpecification> {
  if (next === 'sketch') return sketchStyle(theme.value === 'dark');
  try {
    const style = await fetchStyle(next);
    notice.value = null;
    tileErrors = 0;
    return style;
  } catch {
    // Only the latest choice may fall back: an older, slower download failing changes nothing.
    if (generation === styleGeneration) fallBack();
    return sketchStyle(theme.value === 'dark');
  }
}

/** The online map is not working: show the offline sketch instead, and say so. */
function fallBack() {
  showNotice('The street map could not load, so the offline sketch is shown instead.');
  look.value = 'sketch';
}

// Map pictures that fail to load after the style did (a dropped connection): a few failures in a
// row and the map moves to the sketch rather than staying blank.
let tileErrors = 0;

// ---- What we draw on top of every style: the planned route, the trail, the accuracy circle ----

const lineData = (points: LngLat[]) => ({
  type: 'Feature' as const,
  properties: {},
  geometry: { type: 'LineString' as const, coordinates: points },
});

function trailData() {
  return lineData(props.trail.map((fix) => [fix.lng, fix.lat] as LngLat));
}

function accuracyData() {
  const fix = props.position;
  const ring = fix ? circleRing([fix.lng, fix.lat], fix.accuracyM) : [];
  return {
    type: 'Feature' as const,
    properties: {},
    geometry: { type: 'Polygon' as const, coordinates: fix ? [ring] : [] },
  };
}

function addOverlays(target: MapLibreMap) {
  const dark = theme.value === 'dark';
  const trailColour = dark ? css('--sl-mint') : css('--sl-jade');
  target.addSource('care-planned', { type: 'geojson', data: lineData(props.route.path) });
  target.addSource('care-trail', { type: 'geojson', data: trailData() });
  target.addSource('care-accuracy', { type: 'geojson', data: accuracyData() });
  target.addLayer({
    id: 'care-planned',
    type: 'line',
    source: 'care-planned',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': dark ? '#c9d6d1' : '#46605a',
      'line-width': 3,
      'line-opacity': 0.7,
      'line-dasharray': [1.5, 2],
    },
  });
  target.addLayer({
    id: 'care-trail-casing',
    type: 'line',
    source: 'care-trail',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': dark ? '#0e1715' : '#ffffff', 'line-width': 9 },
  });
  target.addLayer({
    id: 'care-trail',
    type: 'line',
    source: 'care-trail',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': trailColour, 'line-width': 5.5 },
  });
  target.addLayer({
    id: 'care-accuracy',
    type: 'fill',
    source: 'care-accuracy',
    paint: { 'fill-color': trailColour, 'fill-opacity': 0.16 },
  });
  extrusionLayers = ensure3dBuildings(target, dark ? '#38443f' : '#dcd7cf');
  applyThreeD(false);
  showSketchLabels(look.value === 'sketch');
}

function setSource(id: string, data: unknown) {
  const source = map.value?.getSource(id) as GeoJSONSource | undefined;
  source?.setData(data as Parameters<GeoJSONSource['setData']>[0]);
}

// ---- Markers: her, home, and the sketch's place names ----

function markerElement(className: string, html: string): HTMLElement {
  const element = document.createElement('div');
  element.className = className;
  element.setAttribute('aria-hidden', 'true');
  element.innerHTML = html;
  return element;
}

function placeMarkers(target: MapLibreMap) {
  if (!MarkerClass) return;
  const initial = props.seniorName.replace(/^(Mdm|Mr|Mrs|Ms|Madam)\.?\s+/i, '').charAt(0) || '•';
  meMarker = new MarkerClass({
    element: markerElement(
      'walkmap-me',
      `<span class="walkmap-pulse"></span><span class="walkmap-heading"></span><span class="walkmap-face">${initial}</span>`,
    ),
  })
    .setLngLat(centreOf(props.position))
    .addTo(target);
  meMarker.getElement().dataset.testid = 'walk-marker';
  homeMarker = new MarkerClass({
    element: markerElement(
      'walkmap-home',
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/></svg><span>Home</span>',
    ),
    anchor: 'bottom',
  })
    .setLngLat([props.route.home.lng, props.route.home.lat])
    .addTo(target);
  updateMe();
}

function showSketchLabels(on: boolean) {
  for (const marker of labelMarkers) marker.remove();
  labelMarkers = [];
  if (!on || !MarkerClass || !map.value) return;
  for (const label of SKETCH_LABELS) {
    const element = markerElement(`walkmap-label walkmap-label-${label.kind}`, label.text);
    labelMarkers.push(new MarkerClass({ element }).setLngLat(label.at).addTo(map.value));
  }
}

function updateMe() {
  if (!meMarker) return;
  const fix = props.position;
  meMarker.setLngLat(centreOf(fix));
  const element = meMarker.getElement();
  element.classList.toggle('is-replay', !props.live);
  element.classList.toggle('is-hidden', !fix);
  const arrow = element.querySelector<HTMLElement>('.walkmap-heading');
  if (arrow) {
    arrow.style.display = fix?.heading === null || !fix ? 'none' : '';
    arrow.style.transform = `rotate(${(fix?.heading ?? 0) - bearing.value}deg)`;
  }
}

// ---- Camera ----

function applyThreeD(animate = true) {
  const target = map.value;
  if (!target) return;
  for (const id of extrusionLayers) {
    if (target.getLayer(id))
      target.setLayoutProperty(id, 'visibility', threeD.value ? 'visible' : 'none');
  }
  if (!animate) return;
  target.easeTo({
    pitch: threeD.value ? 58 : 0,
    bearing: threeD.value ? -18 : 0,
    duration: reduceMotion() ? 0 : 700,
  });
}

function followNow() {
  const target = map.value;
  if (!target || !props.position) return;
  target.easeTo({ center: centreOf(props.position), duration: reduceMotion() ? 0 : 800 });
}

function zoomBy(delta: number) {
  map.value?.easeTo({ zoom: map.value.getZoom() + delta, duration: reduceMotion() ? 0 : 300 });
}

function pointNorth() {
  map.value?.easeTo({ bearing: 0, duration: reduceMotion() ? 0 : 400 });
}

function chooseLook(next: MapLook) {
  layersOpen.value = false;
  look.value = next;
}

// ---- Setting up ----

onMounted(async () => {
  document.addEventListener('pointerdown', onPointerDown);
  try {
    const [maplibre, worker] = await Promise.all([
      import('maplibre-gl'),
      import('maplibre-gl/dist/maplibre-gl-worker.mjs?url'),
      import('maplibre-gl/dist/maplibre-gl.css'),
    ]);
    maplibre.setWorkerUrl(worker.default);
    MarkerClass = maplibre.Marker;
    if (!container.value) return;
    const style = await styleFor(look.value);
    const created = new maplibre.Map({
      container: container.value,
      style,
      center: centreOf(props.position),
      zoom: 16.2,
      pitch: threeD.value ? 58 : 0,
      bearing: threeD.value ? -18 : 0,
      maxPitch: 70,
      attributionControl: { compact: true },
      locale: {
        'Map.Title': `Map of ${props.seniorName}’s walk. Arrow keys move it, plus and minus zoom.`,
      },
    });
    map.value = created;
    created.on('style.load', () => addOverlays(created));
    created.on('error', () => {
      if (look.value === 'sketch') return;
      tileErrors += 1;
      if (tileErrors >= 4) {
        tileErrors = 0;
        fallBack();
      }
    });
    created.on('data', (event: { dataType?: string; tile?: unknown }) => {
      if (event.dataType === 'source' && event.tile) tileErrors = 0;
    });
    created.once('load', () => {
      placeMarkers(created);
      ready.value = true;
    });
    created.on('rotate', () => {
      bearing.value = created.getBearing();
      updateMe();
    });
    // Dragging or turning the map yourself stops following her, so you can look around.
    const stopFollowing = (event: { originalEvent?: unknown }) => {
      if (event.originalEvent) follow.value = false;
    };
    created.on('dragstart', stopFollowing);
    created.on('rotatestart', stopFollowing);
  } catch (caught) {
    failed.value =
      caught instanceof Error && /webgl/i.test(caught.message)
        ? `This device or browser cannot draw the map (it needs WebGL). ${props.seniorName}’s walk is still described beside it.`
        : `The map could not be shown. ${props.seniorName}’s walk is still described beside it.`;
  }
});

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown);
  if (noticeTimer !== null) window.clearTimeout(noticeTimer);
  map.value?.remove();
  map.value = null;
});

watch(
  () => props.trail,
  () => setSource('care-trail', trailData()),
);

watch(
  () => [props.position, props.live] as const,
  () => {
    setSource('care-accuracy', accuracyData());
    updateMe();
    if (follow.value) followNow();
  },
);

watch(follow, (on) => {
  if (on) followNow();
});

watch(threeD, () => applyThreeD());

watch(
  () => props.route,
  (route) => {
    setSource('care-planned', lineData(route.path));
    homeMarker?.setLngLat([route.home.lng, route.home.lat]);
    if (map.value) map.value.jumpTo({ center: [route.home.lng, route.home.lat] });
  },
);

async function restyle() {
  const target = map.value;
  if (!target) return;
  const generation = ++styleGeneration;
  const style = await styleFor(look.value, generation);
  if (generation !== styleGeneration || map.value !== target) return;
  target.setStyle(style, { diff: false });
}

watch(look, restyle);
// The trail's colour (and the sketch's) follow light and dark mode.
watch(theme, () => void restyle());

const lookLabel = computed(() => LOOKS.find((item) => item.id === look.value)?.label ?? '');
</script>

<template>
  <div
    class="walkmap"
    data-testid="walk-map"
    :data-ready="ready ? 'true' : 'false'"
    :data-look="look"
    :data-three-d="threeD ? 'true' : 'false'"
    :data-follow="follow ? 'true' : 'false'"
  >
    <div v-if="failed" class="walkmap-failed" role="note">
      <Icon name="map" />
      <p class="mb-0">{{ failed }}</p>
    </div>
    <div v-else ref="container" class="walkmap-canvas"></div>

    <!-- Status and anything else the page lays over the map. -->
    <div class="walkmap-overlay">
      <slot />
    </div>

    <p v-if="notice" class="walkmap-notice" role="status">
      <span>{{ notice }}</span>
      <button
        type="button"
        class="btn-close"
        aria-label="Close this message"
        @click="notice = null"
      ></button>
    </p>

    <template v-if="!failed">
      <div class="walkmap-tools walkmap-tools-top">
        <button
          type="button"
          class="walkmap-btn walkmap-btn-text"
          :aria-pressed="threeD"
          title="3D view (off for a flat map)"
          data-testid="map-3d"
          @click="threeD = !threeD"
        >
          3D<span class="visually-hidden"> view</span>
        </button>

        <div ref="layersBox" class="walkmap-layers" @keydown.esc="closeLayers">
          <button
            type="button"
            class="walkmap-btn"
            :aria-expanded="layersOpen"
            aria-controls="walkmap-looks"
            :title="`Map look: ${lookLabel}`"
            data-testid="map-layers"
            @click="layersOpen = !layersOpen"
          >
            <Icon name="layers" /><span class="visually-hidden">Map look: {{ lookLabel }}</span>
          </button>
          <div
            v-show="layersOpen"
            id="walkmap-looks"
            class="walkmap-menu"
            role="group"
            aria-label="Map look"
          >
            <button
              v-for="item in LOOKS"
              :key="item.id"
              type="button"
              class="walkmap-menu-item"
              :aria-pressed="look === item.id"
              @click="chooseLook(item.id)"
            >
              <span class="fw-bold">{{ item.label }}</span>
              <span class="walkmap-menu-hint">{{ item.hint }}</span>
            </button>
          </div>
        </div>

        <button
          type="button"
          class="walkmap-btn"
          :aria-pressed="follow"
          :title="follow ? `Following ${seniorName}` : `Follow ${seniorName}`"
          data-testid="map-follow"
          @click="follow = !follow"
        >
          <Icon name="locate" />
          <span class="visually-hidden">Follow {{ seniorName }}</span>
        </button>

        <button
          type="button"
          class="walkmap-btn"
          title="Point the map north"
          data-testid="map-north"
          @click="pointNorth"
        >
          <span class="walkmap-compass" :style="{ transform: `rotate(${-bearing}deg)` }">
            <Icon name="compass" />
          </span>
          <span class="visually-hidden">Point the map north</span>
        </button>
      </div>

      <div class="walkmap-tools walkmap-tools-bottom">
        <button type="button" class="walkmap-btn" title="Zoom in" @click="zoomBy(1)">
          <Icon name="plus" /><span class="visually-hidden">Zoom in</span>
        </button>
        <button type="button" class="walkmap-btn" title="Zoom out" @click="zoomBy(-1)">
          <Icon name="minus" /><span class="visually-hidden">Zoom out</span>
        </button>
      </div>

      <button
        v-if="!follow && position"
        type="button"
        class="btn btn-primary walkmap-back"
        data-testid="map-back"
        @click="follow = true"
      >
        <Icon name="locate" /> Back to {{ seniorName }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.walkmap {
  position: relative;
  overflow: hidden;
  height: clamp(22rem, 62vh, 42rem);
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius);
  background: var(--sl-mist);
  isolation: isolate;
}

.walkmap-canvas {
  position: absolute;
  inset: 0;
}

.walkmap-failed {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  height: 100%;
  padding: 2rem;
  color: var(--sl-ink-soft);
  text-align: center;
}

.walkmap-failed .sl-icon {
  width: 2.5rem;
  height: 2.5rem;
}

.walkmap-overlay {
  position: absolute;
  top: 0.75rem;
  left: 0.75rem;
  right: 4.5rem;
  z-index: 2;
  pointer-events: none;
}

.walkmap-overlay > :deep(*) {
  pointer-events: auto;
}

.walkmap-notice {
  position: absolute;
  bottom: 5.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  left: 0.75rem;
  right: 4.5rem;
  z-index: 2;
  margin: 0;
  padding: 0.5rem 0.75rem;
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  box-shadow: var(--sl-float);
  font-size: 0.9rem;
}

.walkmap-tools {
  position: absolute;
  right: 0.75rem;
  z-index: 3;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.walkmap-tools-top {
  top: 0.75rem;
}

.walkmap-tools-bottom {
  bottom: 2.25rem;
}

.walkmap-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.9rem;
  height: 2.9rem;
  border: 1px solid var(--sl-line);
  border-radius: 50%;
  background: var(--sl-surface);
  color: var(--sl-ink);
  box-shadow: var(--sl-float);
  transition:
    transform 0.15s var(--sl-ease),
    background-color 0.15s ease;
}

.walkmap-btn:hover {
  background: var(--sl-mist);
}

.walkmap-btn:active {
  transform: scale(0.94);
}

.walkmap-btn[aria-pressed='true'] {
  border-color: var(--sl-jade);
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.walkmap-btn-text {
  font-size: 1rem;
  font-weight: 800;
}

.walkmap-btn .sl-icon {
  width: 1.3rem;
  height: 1.3rem;
}

.walkmap-compass {
  display: inline-flex;
  transition: transform 0.1s linear;
}

.walkmap-layers {
  position: relative;
}

.walkmap-menu {
  position: absolute;
  top: 0;
  right: calc(100% + 0.5rem);
  display: grid;
  gap: 0.25rem;
  width: 15rem;
  padding: 0.4rem;
  border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-sm);
  background: var(--sl-surface);
  box-shadow: var(--sl-float);
}

.walkmap-menu-item {
  display: grid;
  gap: 0.1rem;
  min-height: 2.75rem;
  padding: 0.45rem 0.7rem;
  border: 0;
  border-radius: 0.6rem;
  background: transparent;
  color: var(--sl-ink);
  text-align: left;
}

.walkmap-menu-item:hover {
  background: var(--sl-mist);
}

.walkmap-menu-item[aria-pressed='true'] {
  background: var(--sl-jade-soft);
  color: var(--sl-jade-deep);
}

.walkmap-menu-hint {
  color: var(--sl-ink-soft);
  font-size: 0.85rem;
}

.walkmap-back {
  position: absolute;
  bottom: 2.25rem;
  left: 50%;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  box-shadow: var(--sl-float);
  transform: translateX(-50%);
  white-space: nowrap;
}

@media (max-width: 575.98px) {
  .walkmap {
    height: clamp(20rem, 58vh, 30rem);
  }

  .walkmap-back {
    left: 0.75rem;
    transform: none;
  }
}
</style>

<!-- Markers are made by MapLibre outside Vue's scoped styles, so their styles are global (prefixed). -->
<style>
/* Markers are pictures, not buttons: a drag that starts on one still moves the map. */
.walkmap-me,
.walkmap-home {
  pointer-events: none;
}

.walkmap-me {
  position: relative;
  width: 2.6rem;
  height: 2.6rem;
}

.walkmap-me.is-hidden {
  display: none;
}

.walkmap-face {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 3px solid #fff;
  border-radius: 50%;
  background: var(--sl-jade);
  color: #fff;
  font-weight: 800;
  box-shadow: 0 3px 10px rgb(0 0 0 / 30%);
}

.walkmap-pulse {
  position: absolute;
  inset: -0.6rem;
  border-radius: 50%;
  background: var(--sl-jade);
  opacity: 0.25;
  animation: walkmap-pulse 2s ease-out infinite;
}

.walkmap-heading {
  position: absolute;
  inset: -0.85rem;
  transform-origin: 50% 50%;
}

.walkmap-heading::before {
  position: absolute;
  top: 0;
  left: 50%;
  border-right: 0.45rem solid transparent;
  border-bottom: 0.6rem solid var(--sl-jade);
  border-left: 0.45rem solid transparent;
  content: '';
  transform: translateX(-50%);
}

.walkmap-me.is-replay .walkmap-face {
  background: var(--sl-ink-soft);
}

.walkmap-me.is-replay .walkmap-pulse,
.walkmap-me.is-replay .walkmap-heading {
  display: none;
}

.walkmap-home {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.55rem 0.25rem 0.4rem;
  border: 2px solid var(--sl-surface);
  border-radius: 999px;
  background: var(--sl-ink);
  color: var(--sl-on-ink);
  font-size: 0.8rem;
  font-weight: 800;
  box-shadow: 0 2px 8px rgb(0 0 0 / 25%);
}

.walkmap-label {
  padding: 0.1rem 0.4rem;
  border-radius: 0.4rem;
  background: rgb(255 255 255 / 75%);
  color: #1f4a35;
  font-size: 0.8rem;
  font-weight: 700;
  white-space: nowrap;
  pointer-events: none;
}

.walkmap-label-water {
  color: #1c4d6e;
  font-style: italic;
}

:root[data-bs-theme='dark'] .walkmap-label {
  background: rgb(14 23 21 / 70%);
  color: #bfe3cf;
}

:root[data-bs-theme='dark'] .walkmap-label-water {
  color: #a9d3ef;
}

@keyframes walkmap-pulse {
  from {
    opacity: 0.35;
    transform: scale(0.6);
  }

  to {
    opacity: 0;
    transform: scale(1.4);
  }
}

@media (prefers-reduced-motion: reduce) {
  .walkmap-pulse {
    animation: none;
  }
}
</style>
