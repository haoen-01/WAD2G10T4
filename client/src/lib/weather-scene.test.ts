import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { sceneFor, SKY_COLOURS, timeOfDay, whiteContrast } from './weather-scene';

const NOON = 12;
const NIGHT = 22;

describe('sceneFor', () => {
  it('paints every one of NEA’s forecast words', () => {
    const cases: [string, string, number][] = [
      ['Fair (Day)', 'clear', 0],
      ['Fair & Warm', 'clear', 0],
      ['Partly Cloudy (Night)', 'partly', 0],
      ['Cloudy', 'cloudy', 0],
      ['Hazy', 'haze', 0],
      ['Slightly Hazy', 'haze', 0],
      ['Mist', 'fog', 0],
      ['Fog', 'fog', 0],
      ['Windy', 'partly', 0],
      ['Light Rain', 'rain', 1],
      ['Passing Showers', 'rain', 1],
      ['Light Showers', 'rain', 1],
      ['Moderate Rain', 'rain', 2],
      ['Showers', 'rain', 2],
      ['Heavy Rain', 'rain', 3],
      ['Heavy Showers', 'rain', 3],
      ['Thundery Showers', 'storm', 2],
      ['Heavy Thundery Showers', 'storm', 3],
      ['Heavy Thundery Showers with Gusty Winds', 'storm', 3],
    ];
    for (const [words, sky, rain] of cases) {
      const scene = sceneFor(words, NOON);
      assert.equal(scene.sky, sky, words);
      assert.equal(scene.rain, rain, words);
    }
  });

  it('adds lightning only for thunder, and wind for wind and gusts', () => {
    assert.equal(sceneFor('Thundery Showers', NOON).lightning, true);
    assert.equal(sceneFor('Heavy Rain', NOON).lightning, false);
    assert.equal(sceneFor('Heavy Thundery Showers with Gusty Winds', NOON).windy, true);
    assert.equal(sceneFor('Windy', NOON).windy, true);
    assert.equal(sceneFor('Showers', NOON).windy, false);
  });

  it('falls back to a cloudy sky for words it does not know', () => {
    assert.equal(sceneFor('Something New', NOON).sky, 'cloudy');
  });
});

describe('timeOfDay', () => {
  it('takes NEA’s (Day)/(Night), else the hour', () => {
    assert.equal(timeOfDay('Partly Cloudy (Night)', NOON), 'night');
    assert.equal(timeOfDay('Fair (Day)', NIGHT), 'day');
    assert.equal(timeOfDay('Showers', NOON), 'day');
    assert.equal(timeOfDay('Showers', NIGHT), 'night');
    assert.equal(timeOfDay('Showers', 6), 'night');
    assert.equal(timeOfDay('Showers', 7), 'day');
  });
});

describe('SKY_COLOURS', () => {
  it('keeps white text at 4.5:1 or more on every sky, day and night', () => {
    for (const [name, stops] of Object.entries(SKY_COLOURS)) {
      for (const colour of stops) {
        assert.ok(whiteContrast(colour) >= 4.5, `${name} ${colour}: ${whiteContrast(colour)}`);
      }
    }
  });
});
