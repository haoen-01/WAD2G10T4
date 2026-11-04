import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  NO_DEVICE_VOICE_HINT,
  chooseVoice,
  choosesBrowser,
  englishVoices,
  isOnDeviceVoice,
  kokoroChoice,
  kokoroVoiceOf,
  pickVoice,
  speechChunks,
  voiceHint,
  voiceLabel,
  voiceScore,
} from './speech';

/** A voice the device speaks itself. */
const v = (name: string, lang: string) => ({ name, lang, localService: true });
/** A voice spoken by Microsoft's or Google's servers: the words would leave the device. */
const online = (name: string, lang: string) => ({ name, lang, localService: false });

describe('speech', () => {
  it('prefers a natural Singapore English female voice the device has', () => {
    const mac = [
      v('Daniel', 'en-GB'),
      v('Karen', 'en-AU'),
      v('Samantha (Enhanced)', 'en-US'),
      v('Luna (Premium)', 'en-SG'),
    ];
    assert.equal(pickVoice(mac)?.name, 'Luna (Premium)');
  });

  it('picks the warm female voice the device has, never a male one', () => {
    const device = [
      v('English UK Male', 'en-GB'),
      v('English UK Female', 'en-GB'),
      v('Deutsch', 'de-DE'),
    ];
    assert.equal(pickVoice(device)?.name, 'English UK Female');
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

describe('only on-device voices (the senior’s day never goes to an online voice)', () => {
  const luna = online('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG');
  const aria = online('Microsoft Aria Online (Natural) - English (United States)', 'en-US');
  const google = online('Google US English', 'en-US');
  const zira = v('Microsoft Zira - English (United States)', 'en-US');
  const david = v('Microsoft David - English (United States)', 'en-US');

  it('tells an on-device voice from an online one, and an unknown one is not on-device', () => {
    assert.equal(isOnDeviceVoice(zira), true);
    assert.equal(isOnDeviceVoice(luna), false);
    assert.equal(isOnDeviceVoice({ name: 'Unknown', lang: 'en-US' }), false);
  });

  it('a local voice beats an online "Natural" voice, whatever the order', () => {
    assert.equal(pickVoice([luna, aria, zira])?.name, zira.name);
    assert.equal(pickVoice([zira, luna])?.name, zira.name);
    assert.equal(chooseVoice([luna, google, zira], null)?.name, zira.name);
    assert.ok(voiceScore(zira) > voiceScore(luna));
  });

  it('with only online voices nothing is picked, and the card says it cannot read aloud', () => {
    assert.equal(pickVoice([luna, aria, google]), null);
    assert.equal(chooseVoice([luna, aria, google], null), null);
    assert.equal(voiceHint([luna, aria, google]), NO_DEVICE_VOICE_HINT);
    assert.equal(voiceLabel(null), 'No reading voice on this device');
  });

  it('never uses an online voice, even one the listener chose before', () => {
    assert.equal(chooseVoice([luna, zira], luna.name)?.name, zira.name);
    assert.equal(chooseVoice([luna], luna.name), null);
  });

  it('with only a male on-device voice, reads with it rather than the browser default', () => {
    assert.equal(chooseVoice([luna, david], null)?.name, david.name);
    assert.equal(voiceHint([luna, david]), null);
  });

  it('says nothing about the voice until the browser has listed its voices', () => {
    assert.equal(voiceHint([]), null);
    assert.equal(voiceHint([zira]), null);
  });
});

describe('voice labels', () => {
  it('names the voice plainly for the card', () => {
    assert.equal(
      voiceLabel(online('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG')),
      'Luna · Natural · English (Singapore)',
    );
    assert.equal(
      voiceLabel(v('Microsoft Zira - English (United States)', 'en-US')),
      'Zira · English (United States)',
    );
    assert.equal(voiceLabel(v('Google UK English Female', 'en-GB')), 'Google UK English Female');
    assert.equal(voiceLabel(null), 'No reading voice on this device');
  });
});

describe('choosing a voice', () => {
  const luna = online('Microsoft Luna Online (Natural) - English (Singapore)', 'en-SG');
  const samantha = v('Samantha (Enhanced)', 'en-US');
  const zira = v('Microsoft Zira - English (United States)', 'en-US');
  const german = v('Anna', 'de-DE');

  it('uses the listener’s own choice while the device has it, else the best', () => {
    assert.equal(chooseVoice([samantha, zira], zira.name)?.name, zira.name);
    assert.equal(chooseVoice([samantha, zira], null)?.name, samantha.name);
    assert.equal(
      chooseVoice([samantha, zira], 'A voice from another browser')?.name,
      samantha.name,
    );
  });

  it('lists only the device’s own English voices, best first', () => {
    assert.deepEqual(
      englishVoices([zira, german, samantha, luna]).map((item) => item.name),
      [samantha.name, zira.name],
    );
  });

  it('tells a Kokoro voice choice from a browser voice choice', () => {
    assert.equal(kokoroChoice('af_bella'), 'kokoro:af_bella');
    assert.equal(kokoroVoiceOf('kokoro:af_bella'), 'af_bella');
    assert.equal(kokoroVoiceOf('Microsoft Zira - English (United States)'), null);
    assert.equal(kokoroVoiceOf(null), null);
    assert.equal(choosesBrowser('Microsoft Zira - English (United States)'), true);
    assert.equal(choosesBrowser('kokoro:af_bella'), false);
    assert.equal(choosesBrowser(null), false); // automatic: Kokoro first when it is there
  });
});
