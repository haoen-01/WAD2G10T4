/**
 * Which sky to paint behind the Home weather card, from NEA's 2-hour forecast words ("Thundery
 * Showers", "Partly Cloudy (Night)"). Pure and import-free so `lib/weather-scene.test.ts` checks
 * every word NEA uses, and that white text stays readable on every sky.
 *
 * NEA's words: Fair (Day/Night), Fair & Warm, Partly Cloudy (Day/Night), Cloudy, Hazy, Slightly
 * Hazy, Windy, Mist, Fog, Light Rain, Moderate Rain, Heavy Rain, Passing Showers, Light Showers,
 * Showers, Heavy Showers, Thundery Showers, Heavy Thundery Showers, Heavy Thundery Showers with
 * Gusty Winds. Anything new falls back to a cloudy sky.
 */

export type Sky = 'clear' | 'partly' | 'cloudy' | 'haze' | 'fog' | 'rain' | 'storm';
export type TimeOfDay = 'day' | 'night';

export interface WeatherScene {
  sky: Sky;
  time: TimeOfDay;
  /** 0 none, 1 drizzle, 2 rain, 3 heavy. */
  rain: 0 | 1 | 2 | 3;
  /** How many clouds drift across, 0 to 6. */
  clouds: number;
  lightning: boolean;
  /** Clouds and rain move faster and slant. */
  windy: boolean;
}

/** Day or night: NEA says so for some words; otherwise the hour (7 am to 7 pm is day). */
export function timeOfDay(forecast: string, hour: number): TimeOfDay {
  if (/\(night\)/i.test(forecast)) return 'night';
  if (/\(day\)/i.test(forecast)) return 'day';
  return hour >= 7 && hour < 19 ? 'day' : 'night';
}

export function sceneFor(forecast: string, hour: number): WeatherScene {
  const words = forecast.toLowerCase();
  const time = timeOfDay(forecast, hour);
  const windy = /wind|gust/.test(words);
  const base = { time, windy, lightning: false };

  if (/thunder/.test(words)) {
    return { ...base, sky: 'storm', rain: /heavy/.test(words) ? 3 : 2, clouds: 6, lightning: true };
  }
  if (/rain|shower/.test(words)) {
    const rain = /heavy/.test(words) ? 3 : /light|passing/.test(words) ? 1 : 2;
    return { ...base, sky: 'rain', rain, clouds: rain === 1 ? 4 : 5 };
  }
  if (/fog|mist/.test(words)) return { ...base, sky: 'fog', rain: 0, clouds: 2 };
  if (/haz/.test(words)) return { ...base, sky: 'haze', rain: 0, clouds: 1 };
  if (/partly/.test(words)) return { ...base, sky: 'partly', rain: 0, clouds: 3 };
  if (/fair|sunny|clear/.test(words)) return { ...base, sky: 'clear', rain: 0, clouds: 0 };
  if (/windy/.test(words)) return { ...base, sky: 'partly', rain: 0, clouds: 3, windy: true };
  return { ...base, sky: 'cloudy', rain: 0, clouds: 5 };
}

/**
 * Each sky's gradient, top to bottom. Chosen so white text is at least 4.5:1 on the lightest
 * colour (tested), like the deep blues and greys of a phone's weather app.
 */
export const SKY_COLOURS: Record<`${Sky}-${TimeOfDay}`, [string, string]> = {
  'clear-day': ['#1b4f91', '#2f6db5'],
  'clear-night': ['#0b1730', '#1c2e54'],
  'partly-day': ['#2b5486', '#4a72a0'],
  'partly-night': ['#121d33', '#26354f'],
  'cloudy-day': ['#4b5d70', '#5d6f82'],
  'cloudy-night': ['#1c242e', '#323d4a'],
  'haze-day': ['#5e5c50', '#72705f'],
  'haze-night': ['#24231f', '#3a3830'],
  'fog-day': ['#56606a', '#68717b'],
  'fog-night': ['#1f2429', '#363d44'],
  'rain-day': ['#39495a', '#55677a'],
  'rain-night': ['#151c26', '#2a3440'],
  'storm-day': ['#1f2733', '#36404d'],
  'storm-night': ['#0e1218', '#232a34'],
};

/** WCAG contrast of white text on a `#rrggbb` colour. */
export function whiteContrast(hex: string): number {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
  return 1.05 / (luminance + 0.05);
}
