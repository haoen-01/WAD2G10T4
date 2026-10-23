import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { isWet, plainForecast, summariseForecast, weatherAdvice } from './weather';

describe('summariseForecast', () => {
  it('takes the newest item and sorts the areas', () => {
    const summary = summariseForecast({
      data: {
        items: [
          { forecasts: [{ area: 'Old', forecast: 'Fair' }] },
          {
            valid_period: { text: '9.30 am to 11.30 am' },
            forecasts: [
              { area: 'Toa Payoh', forecast: 'Showers' },
              { area: 'Ang Mo Kio', forecast: 'Partly Cloudy (Day)' },
            ],
          },
        ],
      },
    });
    assert.deepEqual(summary, {
      forecasts: [
        { area: 'Ang Mo Kio', forecast: 'Partly Cloudy (Day)' },
        { area: 'Toa Payoh', forecast: 'Showers' },
      ],
      validFor: '9.30 am to 11.30 am',
    });
  });

  it('gives null for an empty or unexpected body', () => {
    assert.equal(summariseForecast({}), null);
    assert.equal(summariseForecast({ data: { items: [] } }), null);
    assert.equal(summariseForecast({ data: { items: [{ forecasts: [] }] } }), null);
    const malformed = [{ area: 7, forecast: null }] as unknown as {
      area: string;
      forecast: string;
    }[];
    assert.equal(summariseForecast({ data: { items: [{ forecasts: malformed }] } }), null);
  });
});

describe('wording', () => {
  it('spots wet weather', () => {
    assert.equal(isWet('Thundery Showers'), true);
    assert.equal(isWet('Light Rain'), true);
    assert.equal(isWet('Partly Cloudy (Night)'), false);
  });

  it('drops the day/night tag and evens the capitals', () => {
    assert.equal(plainForecast('Partly Cloudy (Day)'), 'Partly cloudy');
    assert.equal(plainForecast('Fair'), 'Fair');
  });

  it('suggests indoors only when it is wet', () => {
    assert.match(weatherAdvice('Showers'), /indoor/);
    assert.match(weatherAdvice('Fair'), /walk/);
  });
});
