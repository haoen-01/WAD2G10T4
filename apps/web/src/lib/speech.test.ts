import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  chooseVoice,
  englishVoices,
  lunaHint,
  isNaturalVoice,
  isPreferredVoice,
  pickVoice,
  speechChunks,
  voiceLabel,
  voiceScore,
} from './speech';

const v = (name: string, lang: string) => ({ name, lang });

describe('speech', () => {
  it('prefers a natural Singapore English female voice when the browser has one (Edge)', () => {
    const edge = [
      v('Microsoft David - English (United States)', 'en-US'),
      v('Microsoft Zira - English (United States)', 'en-US'),
      v('Microsoft Wayne Online (Natural) - English (Singapore)', 'en-SG'),
      v('Microsoft Aria Online (Natural) - English (United States)', 'en-US'),
      v('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG'),
    ];
    assert.equal(pickVoice(edge)?.name, 'Microsoft Luna Online (Natural) - English (Singapore)');
  });

  it('picks the warm female voice Chrome has, never a male one', () => {
    const chrome = [
      v('Google US English', 'en-US'),
      v('Google UK English Male', 'en-GB'),
      v('Google UK English Female', 'en-GB'),
      v('Google Deutsch', 'de-DE'),
    ];
    assert.equal(pickVoice(chrome)?.name, 'Google UK English Female');
  });

  it('takes a robotic female voice only when nothing better exists, and never a male one', () => {
    assert.equal(
      pickVoice([v('Microsoft David', 'en-US'), v('Microsoft Zira', 'en-US')])?.name,
      'Microsoft Zira',
    );
    assert.equal(pickVoice([v('Microsoft David', 'en-US'), v('Daniel', 'en-GB')]), null);
    assert.equal(pickVoice([]), null);
    assert.ok(voiceScore(v('Samantha', 'en-US')) > voiceScore(v('Microsoft Zira', 'en-US')));
    assert.ok(voiceScore(v('Google 普通话', 'zh-CN')) < 0);
  });

  it('reads one sentence at a time and says times clearly', () => {
    assert.deepEqual(
      speechChunks(
        'Good morning, Mdm Lim. You have an eye check-up at 10:30 am with John. Light stretching is at 5 pm. Tomorrow starts at 10am.',
      ),
      [
        'Good morning, Mdm Lim.',
        'You have an eye check-up at 10:30 a.m. with John.',
        'Light stretching is at 5 p.m.',
        'Tomorrow starts at 10 a.m.',
      ],
    );
    assert.deepEqual(speechChunks('   '), []);
  });
});

describe('voice loading and labels', () => {
  it('counts only the neural voices as natural, so a reading waits for them', () => {
    assert.equal(
      isNaturalVoice(v('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG')),
      true,
    );
    assert.equal(isNaturalVoice(v('Microsoft Zira - English (United States)', 'en-US')), false);
    assert.equal(isNaturalVoice(v('Google UK English Female', 'en-GB')), false);
    // A natural voice that is male or not English is never the one waited for.
    assert.equal(
      isNaturalVoice(v('Microsoft Wayne Online (Natural) - English (Singapore)', 'en-SG')),
      false,
    );
  });

  it('picks Luna once Edge has added its online voices, not Zira from the first list', () => {
    const first = [
      v('Microsoft David - English (United States)', 'en-US'),
      v('Microsoft Zira - English (United States)', 'en-US'),
    ];
    const later = [...first, v('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG')];
    assert.equal(pickVoice(first)?.name, 'Microsoft Zira - English (United States)');
    assert.equal(pickVoice(later)?.name, 'Microsoft Luna Online (Natural) - English (Singapore)');
  });

  it('waits only for Luna: Chrome’s natural voice is good enough to use, not to stop waiting', () => {
    const luna = v('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG');
    const chromeNatural = v('Google US English 1 (Natural)', 'en-US');
    const aria = v('Microsoft Aria Online (Natural) - English (United States)', 'en-US');
    assert.equal(isPreferredVoice(luna), true);
    assert.equal(isPreferredVoice(chromeNatural), false);
    assert.equal(isPreferredVoice(aria), false);
    // Both listed: Luna, whatever the order.
    assert.equal(pickVoice([chromeNatural, luna])?.name, luna.name);
    assert.equal(pickVoice([luna, chromeNatural])?.name, luna.name);
    // Without Luna, the natural voice beats the robotic ones.
    assert.equal(
      pickVoice([v('Microsoft Zira - English (United States)', 'en-US'), chromeNatural])?.name,
      chromeNatural.name,
    );
    assert.equal(voiceLabel(chromeNatural), 'Google US English 1 (Natural)');
  });

  it('names the voice plainly for the card', () => {
    assert.equal(
      voiceLabel(v('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG')),
      'Luna · Natural · English (Singapore)',
    );
    assert.equal(
      voiceLabel(v('Microsoft Zira - English (United States)', 'en-US')),
      'Zira · English (United States)',
    );
    assert.equal(voiceLabel(v('Google UK English Female', 'en-GB')), 'Google UK English Female');
    assert.equal(voiceLabel(null), 'Your browser’s default voice');
  });
});

describe('choosing a voice', () => {
  const luna = v('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG');
  const chrome = v('Google US English 1 (Natural)', 'en-US');
  const zira = v('Microsoft Zira - English (United States)', 'en-US');
  const german = v('Google Deutsch', 'de-DE');

  it('uses the listener’s own choice while the browser has it, else the best', () => {
    assert.equal(chooseVoice([chrome, zira], zira.name)?.name, zira.name);
    assert.equal(chooseVoice([chrome, zira], null)?.name, chrome.name);
    assert.equal(chooseVoice([chrome, zira], 'A voice from another browser')?.name, chrome.name);
  });

  it('lists only English voices, best first', () => {
    assert.deepEqual(
      englishVoices([zira, german, chrome, luna]).map((item) => item.name),
      [luna.name, chrome.name, zira.name],
    );
  });

  it('says why Luna is missing: only in Edge, or not loaded in Edge', () => {
    const chromeAgent =
      'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/156.0 Safari/537.36';
    const edgeAgent = `${chromeAgent} Edg/156.0`;
    assert.match(lunaHint([chrome, zira], chromeAgent) ?? '', /only available in Microsoft Edge/);
    assert.match(lunaHint([zira], edgeAgent) ?? '', /has not loaded in Edge/);
    assert.equal(lunaHint([zira, luna], edgeAgent), null);
    assert.equal(lunaHint([], chromeAgent), null);
  });
});
