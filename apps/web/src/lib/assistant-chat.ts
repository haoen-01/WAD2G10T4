/**
 * The Care+ assistant's conversation, in plain data: the messages, what is sent to the API, the
 * suggestions to start with, the page name it is told, and when it may say "Need help?". Pure,
 * so `assistant-chat.test.ts` can check it.
 */

export type ChatRole = 'user' | 'assistant';
export type ReplySource = 'openai' | 'helper' | 'safety' | 'error';

export interface ChatMessage {
  id: number;
  role: ChatRole;
  content: string;
  /** When it was said (ms since 1970). */
  at: number;
  source?: ReplySource;
  /** Things to ask next, offered under an answer. */
  suggestions?: string[];
}

export type Viewer = 'senior' | 'family';

/** The API takes the last 20 turns, each up to 2,000 characters. */
export const MAX_TURNS = 20;
export const MAX_CHARS = 2000;

/**
 * The conversation as the API takes it: only real turns (not error notes), the newest 20, each
 * cut to 2,000 characters, starting with one of hers.
 */
export function forApi(messages: readonly ChatMessage[]): { role: ChatRole; content: string }[] {
  const turns = messages
    .filter((m) => m.source !== 'error' && m.content.trim())
    .map((m) => ({ role: m.role, content: m.content.trim().slice(0, MAX_CHARS) }))
    .slice(-MAX_TURNS);
  while (turns.length && turns[0].role !== 'user') turns.shift();
  return turns;
}

/** What to offer on an empty chat: the questions people ask most, in their own words. */
export function startingSuggestions(viewer: Viewer, page: string | null): string[] {
  const steps = viewer === 'senior' ? 'How many steps today?' : 'How are her steps today?';
  const onPage: Record<string, string> = {
    Badges: 'How do badges work?',
    Walk: 'How does walk sharing work?',
    Calendar: 'How do I add an appointment?',
    Family: 'How do I add a family member?',
  };
  const third = (page && onPage[page]) ?? 'Explain this page';
  return [steps, "What's coming up?", third, 'What can you help with?'];
}

/** The page name the assistant is told, from the address (no ids, no search terms). */
export function pageName(path: string, seniorTab: string | null = null): string {
  if (path === '/') return 'Home';
  if (path.startsWith('/senior')) {
    const tabs: Record<string, string> = {
      today: 'Today',
      calendar: 'Calendar',
      badges: 'Badges',
      family: 'Family',
    };
    return (seniorTab && tabs[seniorTab]) || 'My day';
  }
  const first = path.split('/')[1] ?? '';
  const names: Record<string, string> = {
    walk: 'Walk',
    calendar: 'Calendar',
    family: 'Family',
    groups: 'Family group',
  };
  return names[first] ?? 'Care+';
}

/** "Explain this page", asked on a page, says which page. */
export function expandQuestion(text: string, page: string | null): string {
  if (/^explain this page\.?$/i.test(text.trim()) && page) return `Explain the ${page} page.`;
  return text;
}

// ---- The occasional "Need help?" ----

export const BUBBLE_LINES = ['Need help?', 'Ask me anything', "I'm here if you need me"] as const;
/** Not until a page has been open this long, and never more often than this. */
export const BUBBLE_AFTER_MS = 25_000;
export const BUBBLE_EVERY_MS = 10 * 60_000;
export const BUBBLE_SHOWS_MS = 5_000;

/** Whether the little speech bubble may show now: never while the chat is open or in use. */
export function mayShowBubble(input: {
  now: number;
  pageSince: number;
  lastShown: number | null;
  open: boolean;
  hasChatted: boolean;
}): boolean {
  if (input.open || input.hasChatted) return false;
  if (input.now - input.pageSince < BUBBLE_AFTER_MS) return false;
  return input.lastShown === null || input.now - input.lastShown >= BUBBLE_EVERY_MS;
}

/** Which line the bubble says, taking turns. */
export const bubbleLine = (count: number) => BUBBLE_LINES[count % BUBBLE_LINES.length];

/** "2:05 pm", for a message's time. */
export function timeWords(at: number): string {
  const date = new Date(at);
  const hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours % 12 || 12}:${minutes} ${hours < 12 ? 'am' : 'pm'}`;
}
