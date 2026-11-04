import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  SPEECH_BUSY_CODE,
  SpeechBusyError,
  isBusyBody,
  isSpeechBusy,
  noReadingVoice,
  sentenceFetcher,
} from './read-aloud';

const noWait = async () => undefined;

/** A server that answers each sentence from a script of outcomes, and counts the asks. */
function server(outcomes: Record<number, ('busy' | 'broken' | string)[]>) {
  const asks: number[] = [];
  const fetchOne = async (at: number): Promise<string> => {
    asks.push(at);
    const next = outcomes[at]?.shift() ?? `audio-${at}`;
    if (next === 'busy') throw new SpeechBusyError();
    if (next === 'broken') throw new Error('Kokoro could not speak');
    return next;
  };
  return { asks, fetchOne };
}

describe('read aloud', () => {
  it('tells a busy answer from one that cannot speak', () => {
    assert.equal(isSpeechBusy(new SpeechBusyError()), true);
    assert.equal(isSpeechBusy({ busy: true }), true);
    assert.equal(isSpeechBusy(new Error('Kokoro could not speak')), false);
    assert.equal(isSpeechBusy(null), false);
    assert.equal(isBusyBody(JSON.stringify({ code: SPEECH_BUSY_CODE, detail: 'busy' })), true);
    assert.equal(isBusyBody(JSON.stringify({ detail: 'Kokoro could not load.' })), false);
    assert.equal(isBusyBody('not json'), false);
  });

  it('a sentence asked for ahead and answered busy is asked again on its turn, Kokoro kept', async () => {
    // Sentence 1 is asked for while sentence 0 plays, and the server is busy speaking 0.
    const { asks, fetchOne } = server({ 1: ['busy'] });
    const sentences = sentenceFetcher(fetchOne, { stillWanted: () => true, wait: noWait });
    assert.equal(await sentences.forTurn(0), 'audio-0');
    sentences.prefetch(1);
    await noWait();
    assert.equal(await sentences.forTurn(1), 'audio-1');
    assert.deepEqual(asks, [0, 1, 1]);
  });

  it('a sentence answered busy on its own turn is asked again, a bounded number of times', async () => {
    const { asks, fetchOne } = server({ 0: ['busy', 'busy'] });
    const waits: number[] = [];
    const sentences = sentenceFetcher(fetchOne, {
      stillWanted: () => true,
      retries: 2,
      delayMs: 500,
      wait: async (ms) => void waits.push(ms),
    });
    assert.equal(await sentences.forTurn(0), 'audio-0');
    assert.deepEqual(asks, [0, 0, 0]);
    assert.deepEqual(waits, [500, 500]);

    const stuck = server({ 0: ['busy', 'busy', 'busy', 'busy'] });
    const gives = sentenceFetcher(stuck.fetchOne, { stillWanted: () => true, wait: noWait });
    await assert.rejects(gives.forTurn(0), (error) => isSpeechBusy(error));
    assert.equal(stuck.asks.length, 3); // once, then BUSY_RETRIES more
  });

  it('a voice that cannot speak is not asked again', async () => {
    const { asks, fetchOne } = server({ 0: ['broken'] });
    const sentences = sentenceFetcher(fetchOne, { stillWanted: () => true, wait: noWait });
    await assert.rejects(sentences.forTurn(0), (error) => !isSpeechBusy(error));
    assert.deepEqual(asks, [0]);
  });

  it('a reading that was stopped asks nothing more', async () => {
    let wanted = true;
    const { asks, fetchOne } = server({ 0: ['busy'] });
    const sentences = sentenceFetcher(fetchOne, {
      stillWanted: () => wanted,
      wait: async () => {
        wanted = false;
      },
    });
    await assert.rejects(sentences.forTurn(0));
    assert.deepEqual(asks, [0]);
  });

  it('says there is no voice only once both are known to be missing', () => {
    const none = {
      kokoroKnown: true,
      kokoroReady: false,
      deviceKnown: true,
      deviceHasVoice: false,
    };
    assert.equal(noReadingVoice(none), true);
    assert.equal(noReadingVoice({ ...none, kokoroKnown: false }), false);
    assert.equal(noReadingVoice({ ...none, deviceKnown: false }), false);
    assert.equal(noReadingVoice({ ...none, kokoroReady: true }), false);
    assert.equal(noReadingVoice({ ...none, deviceHasVoice: true }), false);
  });
});
