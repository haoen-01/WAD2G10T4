/**
 * The looks the walk map can take, and the offline sketch map.
 *
 * - "Streets" and "Quiet" are OpenFreeMap's free styles (OpenStreetMap data, no key). The browser
 *   fetches their map pictures from OpenFreeMap, so OpenFreeMap can tell which area is being looked
 *   at. With the simulated walk that is a made-up walk; a real one needs the team's decision (see
 *   UPDATES.md). If they cannot be reached, the map falls back to the sketch.
 * - "Sketch" is drawn here from a few shapes around Bishan–Ang Mo Kio Park: the park, the river,
 *   the roads and blocks of flats (in 3D). It needs no internet, so the demo and the browser tests
 *   work offline. It is a sketch, not a survey: shapes and places are approximate.
 */
import type { Map as MapLibreMap } from 'maplibre-gl';

import type { LngLat } from './geo';

export type StyleSpecification = Exclude<Parameters<MapLibreMap['setStyle']>[0], string | null>;
type LayerSpecification = StyleSpecification['layers'][number];

export type MapLook = 'streets' | 'quiet' | 'sketch';

export const LOOKS: { id: MapLook; label: string; hint: string }[] = [
  { id: 'streets', label: 'Streets', hint: 'Colour street map with 3D buildings' },
  { id: 'quiet', label: 'Quiet', hint: 'Pale map, so the walk stands out' },
  { id: 'sketch', label: 'Sketch (offline)', hint: 'Simple drawing that works without internet' },
];

export const ONLINE_STYLE_URLS: Record<Exclude<MapLook, 'sketch'>, string> = {
  streets: 'https://tiles.openfreemap.org/styles/liberty',
  quiet: 'https://tiles.openfreemap.org/styles/positron',
};

/** Fetches an online style, giving up after `timeoutMs` so a slow network falls back quickly. */
export async function fetchStyle(look: Exclude<MapLook, 'sketch'>, timeoutMs = 6000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(ONLINE_STYLE_URLS[look], { signal: controller.signal });
    if (!response.ok) throw new Error(`Map style answered ${response.status}`);
    return (await response.json()) as StyleSpecification;
  } finally {
    window.clearTimeout(timer);
  }
}

/** Ids of the layers that draw buildings in 3D, adding one if the style has none. */
export function ensure3dBuildings(map: MapLibreMap, colour: string): string[] {
  const style = map.getStyle();
  const existing = style.layers.filter((layer) => layer.type === 'fill-extrusion').map((l) => l.id);
  if (existing.length) return existing;
  const source = Object.entries(style.sources).find(([, spec]) => spec.type === 'vector')?.[0];
  if (!source) return [];
  const firstLabel = style.layers.find((layer) => layer.type === 'symbol')?.id;
  map.addLayer(
    {
      id: 'care-3d-buildings',
      type: 'fill-extrusion',
      source,
      'source-layer': 'building',
      minzoom: 14,
      paint: {
        'fill-extrusion-color': colour,
        'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 10],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': 0.85,
      },
    },
    firstLabel,
  );
  return ['care-3d-buildings'];
}

// ---- The sketch ----

const PARK: LngLat[] = [
  [103.8355, 1.3628],
  [103.8362, 1.3614],
  [103.8385, 1.3609],
  [103.842, 1.3613],
  [103.8455, 1.3617],
  [103.848, 1.3622],
  [103.8492, 1.3634],
  [103.8484, 1.3647],
  [103.8455, 1.3652],
  [103.842, 1.365],
  [103.8395, 1.3644],
  [103.837, 1.3639],
  [103.8355, 1.3628],
];

const RIVER: LngLat[] = [
  [103.835, 1.3619],
  [103.8365, 1.3621],
  [103.8378, 1.3622],
  [103.8392, 1.36265],
  [103.8408, 1.363],
  [103.8423, 1.3633],
  [103.8438, 1.36345],
  [103.8452, 1.36355],
  [103.8463, 1.3637],
  [103.8478, 1.3638],
  [103.8495, 1.3636],
];

const ROADS: LngLat[][] = [
  [
    [103.834, 1.3657],
    [103.852, 1.3657],
  ],
  [
    [103.834, 1.3603],
    [103.852, 1.3603],
  ],
  [
    [103.8345, 1.359],
    [103.8345, 1.368],
  ],
  [
    [103.8442, 1.3657],
    [103.8442, 1.369],
  ],
];

/** A block of flats: a rectangle `w` × `d` metres around `centre`, `h` metres tall. */
function block(centre: LngLat, w: number, d: number, h: number, kind = 'flat') {
  const dx = w / 2 / (111_320 * Math.cos((centre[1] * Math.PI) / 180));
  const dy = d / 2 / 110_574;
  const [x, y] = centre;
  return {
    type: 'Feature' as const,
    properties: { height: h, kind },
    geometry: {
      type: 'Polygon' as const,
      coordinates: [
        [
          [x - dx, y - dy],
          [x + dx, y - dy],
          [x + dx, y + dy],
          [x - dx, y + dy],
          [x - dx, y - dy],
        ],
      ],
    },
  };
}

const BLOCKS = [
  block([103.8442, 1.36672], 55, 14, 42, 'home'),
  block([103.8455, 1.367], 30, 22, 5, 'centre'),
  ...[103.8405, 103.8422, 103.847, 103.8487].flatMap((lng, i) => [
    block([lng, 1.3667], 55, 14, 36 + (i % 2) * 9),
    block([lng, 1.3679], 55, 14, 45 - (i % 2) * 6),
  ]),
  block([103.8442, 1.3681], 55, 14, 39),
  ...[103.8375, 103.8395, 103.8415, 103.8435, 103.8455, 103.8475].flatMap((lng, i) => [
    block([lng, 1.3594], 50, 14, 33 + (i % 3) * 6),
    block([lng, 1.3583], 50, 14, 42 - (i % 3) * 5),
  ]),
];

const line = (coordinates: LngLat[]) => ({
  type: 'Feature' as const,
  properties: {},
  geometry: { type: 'LineString' as const, coordinates },
});

/** Words shown on the sketch (it has no font server, so the map draws them as small labels). */
export const SKETCH_LABELS: { text: string; at: LngLat; kind: 'park' | 'water' }[] = [
  { text: 'Bishan–Ang Mo Kio Park', at: [103.8402, 1.3641], kind: 'park' },
  { text: 'Kallang River', at: [103.8478, 1.36415], kind: 'water' },
];

export function sketchStyle(dark: boolean): StyleSpecification {
  const c = dark
    ? {
        land: '#121b18',
        park: '#1c3328',
        water: '#21445c',
        road: '#2c3834',
        roadEdge: '#0b1210',
        block: '#34403b',
        home: '#4a6a5f',
        centre: '#6b5a2e',
      }
    : {
        land: '#eef1ec',
        park: '#cde6c7',
        water: '#9ccbe6',
        road: '#ffffff',
        roadEdge: '#d2d8d4',
        block: '#dcd7cf',
        home: '#b9d8cb',
        centre: '#f0dfae',
      };
  const layers: LayerSpecification[] = [
    { id: 'land', type: 'background', paint: { 'background-color': c.land } },
    { id: 'park', type: 'fill', source: 'park', paint: { 'fill-color': c.park } },
    {
      id: 'river',
      type: 'line',
      source: 'river',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': c.water,
        'line-width': ['interpolate', ['linear'], ['zoom'], 13, 4, 17, 26],
      },
    },
    {
      id: 'road-edge',
      type: 'line',
      source: 'roads',
      layout: { 'line-cap': 'round' },
      paint: {
        'line-color': c.roadEdge,
        'line-width': ['interpolate', ['linear'], ['zoom'], 13, 4, 17, 22],
      },
    },
    {
      id: 'road',
      type: 'line',
      source: 'roads',
      layout: { 'line-cap': 'round' },
      paint: {
        'line-color': c.road,
        'line-width': ['interpolate', ['linear'], ['zoom'], 13, 2.5, 17, 18],
      },
    },
    {
      id: 'blocks',
      type: 'fill-extrusion',
      source: 'blocks',
      paint: {
        'fill-extrusion-color': [
          'match',
          ['get', 'kind'],
          'home',
          c.home,
          'centre',
          c.centre,
          c.block,
        ],
        'fill-extrusion-height': ['get', 'height'],
        'fill-extrusion-opacity': 0.92,
      },
    },
  ];
  return {
    version: 8,
    name: 'Care+ sketch',
    sources: {
      park: {
        type: 'geojson',
        data: {
          type: 'Feature',
          properties: {},
          geometry: { type: 'Polygon', coordinates: [PARK] },
        },
      },
      river: { type: 'geojson', data: line(RIVER) },
      roads: { type: 'geojson', data: { type: 'FeatureCollection', features: ROADS.map(line) } },
      blocks: { type: 'geojson', data: { type: 'FeatureCollection', features: BLOCKS } },
    },
    layers,
  };
}
