import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  BUBBLE_AFTER_MS,
  BUBBLE_EVERY_MS,
  bubbleLine,
  expandQuestion,
  forApi,
  MAX_CHARS,
  MAX_TURNS,
  mayShowBubble,
  pageName,
  startingSuggestions,
  type ChatMessage,
} from './assistant-chat';

let id = 0;
const msg = (role: ChatMessage['role'], content: string, source?: ChatMessage['source']) => ({
  id: (id += 1),
  role,
  content,
  at: id,
  source,
});

describe('what is sent to the API', () => {
  it('sends the real turns, newest 20, starting with hers', () => {
    const chat = [
      msg('assistant', 'Hello!'),
      msg('user', 'hi'),
      msg('assistant', 'Sorry, I could not reach Care+.', 'error'),
      msg('user', '  steps?  '),
    ];
    assert.deepEqual(forApi(chat), [
      { role: 'user', content: 'hi' },
      { role: 'user', content: 'steps?' },
    ]);
    const long = Array.from({ length: 30 }, (_, i) => msg(i % 2 ? 'assistant' : 'user', `m${i}`));
    const sent = forApi(long);
    assert.ok(sent.length <= MAX_TURNS);
    assert.equal(sent[0].role, 'user');
    assert.equal(sent[sent.length - 1].content, 'm29');
  });

  it('cuts a very long message to what the API takes', () => {
    assert.equal(forApi([msg('user', 'x'.repeat(5000))])[0].content.length, MAX_CHARS);
  });
});

describe('starting points', () => {
  it('speaks to her, or about her, and fits the page', () => {
    assert.deepEqual(startingSuggestions('senior', 'Badges'), [
      'How many steps today?',
      "What's coming up?",
      'How do badges work?',
      'What can you help with?',
    ]);
    assert.equal(startingSuggestions('family', 'Home')[0], 'How are her steps today?');
    assert.equal(startingSuggestions('family', 'Home')[2], 'Explain this page');
  });

  it('names the page from the address only', () => {
    assert.equal(pageName('/'), 'Home');
    assert.equal(pageName('/senior', 'badges'), 'Badges');
    assert.equal(pageName('/senior'), 'My day');
    assert.equal(pageName('/walk'), 'Walk');
    assert.equal(pageName('/groups/start'), 'Family group');
    assert.equal(pageName('/something?q=secret'), 'Care+');
  });

  it('turns "Explain this page" into which page', () => {
    assert.equal(expandQuestion('Explain this page', 'Walk'), 'Explain the Walk page.');
    assert.equal(expandQuestion('How do badges work?', 'Walk'), 'How do badges work?');
  });
});

describe('the occasional "Need help?"', () => {
  const base = { now: 100_000, pageSince: 0, lastShown: null, open: false, hasChatted: false };

  it('waits a while on a page, then shows, then not again for ten minutes', () => {
    assert.equal(mayShowBubble({ ...base, now: BUBBLE_AFTER_MS - 1 }), false);
    assert.equal(mayShowBubble(base), true);
    assert.equal(mayShowBubble({ ...base, lastShown: base.now - 60_000 }), false);
    assert.equal(mayShowBubble({ ...base, lastShown: base.now - BUBBLE_EVERY_MS }), true);
  });

  it('never while the chat is open or once she has used it', () => {
    assert.equal(mayShowBubble({ ...base, open: true }), false);
    assert.equal(mayShowBubble({ ...base, hasChatted: true }), false);
  });

  it('takes turns with what it says', () => {
    assert.deepEqual([0, 1, 2, 3].map(bubbleLine), [
      'Need help?',
      'Ask me anything',
      "I'm here if you need me",
      'Need help?',
    ]);
  });
});
