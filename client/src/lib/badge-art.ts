/**
 * The drawing behind each walking badge: an enamel pin with a gold rim, drawn in a 200 × 200 box.
 * Pure data (outline paths, colours and the picture's parts), so `components/badges/BadgeMedal.vue`
 * only has to paint it and `lib/badge-art.test.ts` can check it. Every design here is original.
 */
import type { BadgeLook, BadgeMotif, BadgeShape, BadgeTone } from './badges';

export const CENTRE = 100;

type Point = [number, number];

const round1 = (value: number) => Math.round(value * 10) / 10;
const pt = ([x, y]: Point) => `${round1(x)} ${round1(y)}`;

/** A closed outline through `points`, each corner rounded off by up to `radius`. */
export function roundedPolygon(points: readonly Point[], radius: number): string {
  const n = points.length;
  const parts: string[] = [];
  for (let i = 0; i < n; i += 1) {
    const prev = points[(i - 1 + n) % n];
    const here = points[i];
    const next = points[(i + 1) % n];
    const toPrev = Math.hypot(prev[0] - here[0], prev[1] - here[1]);
    const toNext = Math.hypot(next[0] - here[0], next[1] - here[1]);
    const r = Math.min(radius, toPrev / 2, toNext / 2);
    const a: Point = [
      here[0] + ((prev[0] - here[0]) * r) / toPrev,
      here[1] + ((prev[1] - here[1]) * r) / toPrev,
    ];
    const b: Point = [
      here[0] + ((next[0] - here[0]) * r) / toNext,
      here[1] + ((next[1] - here[1]) * r) / toNext,
    ];
    parts.push(`${i === 0 ? 'M' : 'L'}${pt(a)} Q${pt(here)} ${pt(b)}`);
  }
  return `${parts.join(' ')} Z`;
}

function polar(radius: number, degrees: number, centre: Point = [CENTRE, CENTRE]): Point {
  const rad = (degrees * Math.PI) / 180;
  return [centre[0] + radius * Math.cos(rad), centre[1] + radius * Math.sin(rad)];
}

function scalloped(lobes: number, radius: number): string {
  const points = Array.from({ length: lobes }, (_, i) => polar(radius, (360 / lobes) * i - 90));
  const chord = Math.hypot(points[1][0] - points[0][0], points[1][1] - points[0][1]);
  const lobe = round1(chord * 0.56);
  return `M${pt(points[0])} ${points
    .map((_, i) => `A${lobe} ${lobe} 0 0 1 ${pt(points[(i + 1) % lobes])}`)
    .join(' ')} Z`;
}

/** Each outline, filling most of the box (the rim is this; the enamel is a smaller copy). */
export const SHAPES: Record<BadgeShape, string> = {
  circle: `M100 7 A93 93 0 1 1 99.9 7 Z`,
  hexagon: roundedPolygon(
    Array.from({ length: 6 }, (_, i) => polar(96, 60 * i - 90)),
    18,
  ),
  shield:
    'M100 5 C128 17 156 21 183 17 C187 86 176 146 100 195 C24 146 13 86 17 17 C44 21 72 17 100 5 Z',
  rosette: scalloped(18, 86),
  star: roundedPolygon(
    Array.from({ length: 10 }, (_, i) => polar(i % 2 ? 62 : 98, 36 * i - 90, [100, 104])),
    9,
  ),
  pennant: roundedPolygon(
    [
      [22, 10],
      [178, 10],
      [178, 190],
      [100, 162],
      [22, 190],
    ],
    16,
  ),
};

/** How much smaller each layer is than the outline: the gold rim, its inner lip, the enamel. */
export const LAYERS = { lip: 0.92, field: 0.85, wire: 0.9 } as const;

/** `transform` for a copy of the outline scaled about the centre. */
export function inset(scale: number): string {
  return `translate(${CENTRE} ${CENTRE}) scale(${scale}) translate(${-CENTRE} ${-CENTRE})`;
}

export interface Tone {
  /** Enamel: light (top left), main, deep (bottom right). */
  hi: string;
  mid: string;
  lo: string;
  /** Two inlay colours for the picture. */
  a1: string;
  a2: string;
}

export const TONES: Record<BadgeTone, Tone> = {
  teal: { hi: '#6fe6d9', mid: '#14a99b', lo: '#0a5753', a1: '#ffd36b', a2: '#f6f1e2' },
  jade: { hi: '#8ae9a9', mid: '#22a35a', lo: '#0d5430', a1: '#f7e58c', a2: '#eaf7ee' },
  orange: { hi: '#ffbe6e', mid: '#f07a1a', lo: '#953a05', a1: '#ffe08a', a2: '#fff4de' },
  coral: { hi: '#ffa6a6', mid: '#ef4f68', lo: '#951c39', a1: '#ffd3a3', a2: '#ffebee' },
  violet: { hi: '#c1adff', mid: '#6f4be0', lo: '#2f1d75', a1: '#ffcf6b', a2: '#eee8ff' },
  sky: { hi: '#9be0ff', mid: '#2f9be3', lo: '#104f86', a1: '#ffe17a', a2: '#eaf7ff' },
  sun: { hi: '#ffec92', mid: '#f5b623', lo: '#9a6508', a1: '#ff8f4d', a2: '#fff8d9' },
  ocean: { hi: '#7fc0ff', mid: '#1f5fd1', lo: '#0b276a', a1: '#84e6d3', a2: '#e8f0ff' },
  ruby: { hi: '#ff8597', mid: '#d61f45', lo: '#6b0a21', a1: '#ffd070', a2: '#ffe8ec' },
  plum: { hi: '#e8acf3', mid: '#a23dbd', lo: '#4c165c', a1: '#ffd56b', a2: '#f9eafc' },
  emerald: { hi: '#86f2c5', mid: '#12a36d', lo: '#064c32', a1: '#ffe27a', a2: '#e8fbf2' },
  forest: { hi: '#a7e286', mid: '#3f9a3a', lo: '#1a4e1d', a1: '#86d4ff', a2: '#fff4c8' },
  rose: { hi: '#ffbdd7', mid: '#e9578f', lo: '#86184a', a1: '#ffe08a', a2: '#fff1f7' },
  indigo: { hi: '#a6b2ff', mid: '#3f4fd6', lo: '#1a206a', a1: '#ffcf6b', a2: '#eff1ff' },
};

/** Polished gold, light catching the top left (stops for a linear gradient). */
export const GOLD = [
  ['0', '#7d5814'],
  ['0.18', '#f8e3a0'],
  ['0.38', '#c4953a'],
  ['0.55', '#fff0bd'],
  ['0.78', '#b0802a'],
  ['1', '#5f420e'],
] as const;

/** The darker gold of the rim's inner lip, lit from the other side. */
export const GOLD_LIP = [
  ['0', '#f3d78f'],
  ['0.45', '#9b7024'],
  ['1', '#4e350a'],
] as const;

/** One part of a picture. `fill` names a colour; `wire` outlines it in gold, as cloisonné does. */
export interface Part {
  tag: 'path' | 'circle' | 'ellipse' | 'rect' | 'text';
  attrs: Record<string, string | number>;
  fill: keyof Tone | 'gold' | 'none';
  wire?: boolean;
  /** Text only: what it says. */
  text?: string;
  /** A stroke in this colour instead of a fill (paths, roads). */
  line?: keyof Tone | 'gold';
  lineWidth?: number;
}

const sunRays = (cx: number, cy: number, inner: number, outer: number, from = 200, to = 340) =>
  Array.from({ length: 7 }, (_, i): Part => {
    const angle = from + ((to - from) / 6) * i;
    const [x1, y1] = polar(inner, angle, [cx, cy]);
    const [x2, y2] = polar(outer, angle, [cx, cy]);
    return {
      tag: 'path',
      attrs: { d: `M${round1(x1)} ${round1(y1)} L${round1(x2)} ${round1(y2)}` },
      fill: 'none',
      line: 'gold',
      lineWidth: 4,
    };
  });

/** Big lettering, gold with a dark edge, sized to fit. */
function lettering(text: string, y: number, size: number): Part {
  return {
    tag: 'text',
    attrs: { x: CENTRE, y, 'font-size': size, 'text-anchor': 'middle' },
    fill: 'gold',
    text,
  };
}

function leafBranch(side: 1 | -1): Part[] {
  const parts: Part[] = [
    {
      tag: 'path',
      attrs: {
        d: side === -1 ? 'M92 160 C58 150 40 120 46 78' : 'M108 160 C142 150 160 120 154 78',
      },
      fill: 'none',
      line: 'gold',
      lineWidth: 3,
    },
  ];
  const along: [number, number, number][] = [
    [80, 155, 20],
    [66, 145, 40],
    [55, 130, 60],
    [48, 112, 75],
    [46, 94, 88],
  ];
  for (const [x, y, tilt] of along) {
    parts.push({
      tag: 'ellipse',
      attrs: {
        cx: side === -1 ? x : 200 - x,
        cy: y,
        rx: 10,
        ry: 4.6,
        transform: `rotate(${side === -1 ? -tilt : tilt} ${side === -1 ? x : 200 - x} ${y})`,
      },
      fill: 'a1',
      wire: true,
    });
  }
  return parts;
}

/** A shoe print's front and heel, centred on 0 0 (moved into place with a transform). */
const SOLE =
  'M0 -32 C12 -32 17 -20 15 -7 C13 3 9 7 9 13 L-9 13 C-9 7 -14 3 -15 -7 C-17 -20 -12 -32 0 -32 Z';
/** A winding walking path, from the foot of the badge up towards the star. */
const ROAD = 'M86 200 C56 176 74 152 104 140 C128 130 124 114 100 100';
const HEEL = 'M-8.5 18 L8.5 18 C9.5 27 6 33 0 33 C-6 33 -9.5 27 -8.5 18 Z';

/** The picture on each badge, drawn over the enamel. */
export function motifParts(look: BadgeLook): Part[] {
  const label = look.label ?? '';
  const size = label.length <= 2 ? 66 : label.length === 3 ? 54 : 44;
  const motifs: Record<BadgeMotif, () => Part[]> = {
    footprints: (): Part[] => [
      {
        tag: 'path',
        attrs: { d: 'M10 146 C60 124 140 156 190 134 L190 200 L10 200 Z' },
        fill: 'lo',
        wire: true,
      },
      ...(
        [
          [74, 122, -12],
          [124, 82, 12],
        ] as const
      ).flatMap(([x, y, tilt]): Part[] => [
        {
          tag: 'path',
          attrs: { d: SOLE, transform: `translate(${x} ${y}) rotate(${tilt})` },
          fill: 'a2',
          wire: true,
        },
        {
          tag: 'path',
          attrs: { d: HEEL, transform: `translate(${x} ${y}) rotate(${tilt})` },
          fill: 'a2',
          wire: true,
        },
      ]),
      { tag: 'circle', attrs: { cx: 150, cy: 156, r: 7 }, fill: 'a1', wire: true },
      { tag: 'circle', attrs: { cx: 56, cy: 64, r: 5 }, fill: 'a1', wire: true },
    ],
    numeral: (): Part[] => [
      { tag: 'circle', attrs: { cx: 100, cy: 70, r: 20 }, fill: 'a1', wire: true },
      ...sunRays(100, 70, 27, 42),
      {
        tag: 'path',
        attrs: { d: 'M8 118 C58 100 142 132 192 112 L192 200 L8 200 Z' },
        fill: 'lo',
        wire: true,
      },
      lettering(label, 152 + (66 - size) * 0.25, size),
    ],
    week: (): Part[] => [
      ...Array.from({ length: 7 }, (_, i): Part => {
        const [cx, cy] = polar(60, 205 + (130 / 6) * i, [100, 118]);
        return {
          tag: 'circle',
          attrs: { cx: round1(cx), cy: round1(cy), r: 7 },
          fill: i < 5 ? 'gold' : 'a2',
          wire: i >= 5,
        };
      }),
      { tag: 'circle', attrs: { cx: 100, cy: 128, r: 28 }, fill: 'a1', wire: true },
      {
        tag: 'path',
        attrs: { d: 'M10 152 Q56 112 100 138 Q144 112 190 152 L190 200 L10 200 Z' },
        fill: 'lo',
        wire: true,
      },
      {
        tag: 'path',
        attrs: { d: 'M10 172 Q100 140 190 172 L190 200 L10 200 Z' },
        fill: 'mid',
        wire: true,
      },
    ],
    weekend: (): Part[] => [
      { tag: 'circle', attrs: { cx: 80, cy: 92, r: 30 }, fill: 'a2', wire: true },
      { tag: 'circle', attrs: { cx: 120, cy: 92, r: 30 }, fill: 'a1', wire: true },
      {
        tag: 'text',
        attrs: { x: 72, y: 102, 'font-size': 28, 'text-anchor': 'middle' },
        fill: 'lo',
        text: 'S',
      },
      {
        tag: 'text',
        attrs: { x: 128, y: 102, 'font-size': 28, 'text-anchor': 'middle' },
        fill: 'lo',
        text: 'S',
      },
      {
        tag: 'path',
        attrs: { d: 'M10 140 Q60 112 104 134 Q150 110 190 132 L190 200 L10 200 Z' },
        fill: 'lo',
        wire: true,
      },
      { tag: 'path', attrs: { d: 'M150 132 L160 104 L170 132 Z' }, fill: 'mid', wire: true },
      { tag: 'path', attrs: { d: 'M32 136 L42 110 L52 136 Z' }, fill: 'mid', wire: true },
    ],
    month: (): Part[] => [
      {
        tag: 'rect',
        attrs: { x: 46, y: 50, width: 108, height: 104, rx: 12 },
        fill: 'a2',
        wire: true,
      },
      {
        tag: 'rect',
        attrs: { x: 46, y: 50, width: 108, height: 24, rx: 12 },
        fill: 'a1',
        wire: true,
      },
      { tag: 'rect', attrs: { x: 70, y: 40, width: 8, height: 20, rx: 4 }, fill: 'gold' },
      { tag: 'rect', attrs: { x: 122, y: 40, width: 8, height: 20, rx: 4 }, fill: 'gold' },
      ...Array.from({ length: 20 }, (_, i): Part => ({
        tag: 'rect',
        attrs: {
          x: 56 + (i % 5) * 18.5,
          y: 82 + Math.floor(i / 5) * 17,
          width: 13,
          height: 12,
          rx: 3,
        },
        fill: 'mid',
      })),
    ],
    marathon: (): Part[] => [
      { tag: 'circle', attrs: { cx: 100, cy: 106, r: 42 }, fill: 'lo', wire: true },
      {
        tag: 'circle',
        attrs: { cx: 100, cy: 106, r: 34 },
        fill: 'none',
        line: 'gold',
        lineWidth: 1.5,
      },
      lettering(label, 114, 40),
      {
        tag: 'text',
        attrs: { x: 100, y: 133, 'font-size': 13, 'text-anchor': 'middle', 'letter-spacing': 3 },
        fill: 'a2',
        text: look.sub ?? '',
      },
    ],
    laurel: (): Part[] => [
      ...leafBranch(-1),
      ...leafBranch(1),
      lettering(label, 114, label.length > 3 ? 32 : 42),
      {
        tag: 'path',
        attrs: { d: 'M70 136 L130 136' },
        fill: 'none',
        line: 'gold',
        lineWidth: 2,
      },
    ],
    peak: (): Part[] => [
      { tag: 'circle', attrs: { cx: 146, cy: 60, r: 13 }, fill: 'a1', wire: true },
      {
        tag: 'path',
        attrs: { d: 'M14 168 L70 98 L98 128 L134 84 L190 168 Z' },
        fill: 'mid',
        wire: true,
      },
      {
        tag: 'path',
        attrs: { d: 'M38 168 L96 72 L156 168 Z' },
        fill: 'lo',
        wire: true,
      },
      {
        tag: 'path',
        attrs: { d: 'M96 72 L110 95 L102 92 L96 100 L89 91 L82 95 Z' },
        fill: 'a2',
        wire: true,
      },
      { tag: 'path', attrs: { d: 'M96 72 L96 40' }, fill: 'none', line: 'gold', lineWidth: 3 },
      { tag: 'path', attrs: { d: 'M96 40 L122 48 L96 57 Z' }, fill: 'a1', wire: true },
    ],
    park: (): Part[] => [
      { tag: 'circle', attrs: { cx: 134, cy: 58, r: 14 }, fill: 'a2', wire: true },
      {
        tag: 'path',
        attrs: { d: 'M14 128 Q100 96 186 128 L186 200 L14 200 Z' },
        fill: 'lo',
        wire: true,
      },
      { tag: 'ellipse', attrs: { cx: 100, cy: 150, rx: 54, ry: 16 }, fill: 'a1', wire: true },
      {
        tag: 'ellipse',
        attrs: { cx: 100, cy: 146, rx: 72, ry: 30 },
        fill: 'none',
        line: 'a2',
        lineWidth: 5,
      },
      { tag: 'path', attrs: { d: 'M44 124 L60 80 L76 124 Z' }, fill: 'mid', wire: true },
      { tag: 'path', attrs: { d: 'M62 118 L74 88 L86 118 Z' }, fill: 'mid', wire: true },
      { tag: 'path', attrs: { d: 'M124 120 L140 74 L156 120 Z' }, fill: 'mid', wire: true },
    ],
    paths: (): Part[] => [
      {
        tag: 'path',
        attrs: {
          d: 'M100 40 L105 54 L119 56 L108 65 L112 80 L100 72 L88 80 L92 65 L81 56 L95 54 Z',
        },
        fill: 'a1',
        wire: true,
      },
      { tag: 'path', attrs: { d: 'M34 128 L46 96 L58 128 Z' }, fill: 'mid', wire: true },
      { tag: 'path', attrs: { d: 'M142 120 L154 88 L166 120 Z' }, fill: 'mid', wire: true },
      {
        tag: 'path',
        attrs: { d: 'M10 132 Q100 108 190 130 L190 200 L10 200 Z' },
        fill: 'lo',
        wire: true,
      },
      { tag: 'path', attrs: { d: ROAD }, fill: 'none', line: 'a2', lineWidth: 15 },
      {
        tag: 'path',
        attrs: { d: ROAD, 'stroke-dasharray': '7 7' },
        fill: 'none',
        line: 'gold',
        lineWidth: 2,
      },
    ],
    challenge: (): Part[] => [
      ...Array.from({ length: 12 }, (_, i): Part => {
        const [cx, cy] = polar(66, 30 * i - 90);
        return { tag: 'circle', attrs: { cx: round1(cx), cy: round1(cy), r: 3.4 }, fill: 'gold' };
      }),
      { tag: 'circle', attrs: { cx: 100, cy: 100, r: 56 }, fill: 'lo', wire: true },
      {
        tag: 'path',
        attrs: { d: 'M46 118 C70 104 130 128 154 112 L150 132 C120 150 80 150 50 132 Z' },
        fill: 'mid',
        wire: true,
      },
      lettering(label, 106, 40),
      {
        tag: 'text',
        attrs: { x: 100, y: 132, 'font-size': 14, 'text-anchor': 'middle', 'letter-spacing': 4 },
        fill: 'a2',
        text: look.sub ?? '',
      },
      { tag: 'circle', attrs: { cx: 100, cy: 34, r: 6 }, fill: 'a1', wire: true },
    ],
  };
  return motifs[look.motif]();
}

/** How much smaller the back's lettering is on a narrow outline. */
export function backTextScale(shape: BadgeShape): number {
  return shape === 'star' ? 0.78 : shape === 'rosette' ? 0.92 : 1;
}
