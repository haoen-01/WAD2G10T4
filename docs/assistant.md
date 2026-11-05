# Kaki, the Care+ assistant

A chat helper on every screen for seniors and their families. Decisions and data rules are in
[ADR 0013](adr/0013-care-plus-assistant.md); this page is how it works and how to change it.

## Turning on the AI

1. Put the key in the **API's** `.env` (repo root or `server/.env`), never in a `VITE_` variable:

   ```bash
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-5-mini
   ```

2. Restart the API (`pnpm dev`). Under `CAREPLUS_RUNTIME_PROFILE=offline` (`pnpm demo:offline`,
   Playwright) the key is ignored and the built-in helper answers.

Each answer says where it came from in `source`: `openai`, `helper` (no key, offline, or OpenAI
could not be reached) or `safety` (a fixed answer for an emergency or a medicine question).

## How it is built

| Part                                          | What it does                                                                                                                                       |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `server/src/silverloop/assistant.py`          | Safety answers, the built-in helper, the OpenAI call (`httpx`), the instructions, and the fair-use limit.                                          |
| `server/src/silverloop/assistant_routes.py`   | `POST /v1/assistant/chat`: who may ask about whom (`check_reader`), and the facts about the senior.                                                |
| `services/careApi.ts` → `askAssistant`        | The only browser call.                                                                                                                             |
| `composables/useAssistant.ts`                 | The conversation (in memory), mood, unread count, `assistantLookAt`.                                                                               |
| `composables/useSpeechInput.ts`               | Voice typing with the Web Speech API, and its first-use notice.                                                                                    |
| `components/assistant/AssistantDock.vue`      | The orb on screen: drag, snap to an edge, arrow keys, remembered place, "Need help?", the chat growing out of the orb. Mounted in `AppLayout.vue`. |
| `components/assistant/AssistantOrb.vue`       | The face: glass orb, swirling rim, eyes that follow the pointer, blinking and moods.                                                               |
| `AssistantMessages.vue`, `AssistantInput.vue` | The conversation, suggestions, typing dots; the message box, microphone and Send.                                                                  |
| `lib/assistant-geometry.ts`                   | Eye maths (`atan2`, limited radius), blink timing, keeping on screen, edge snap, where the chat opens. Tested.                                     |
| `lib/assistant-chat.ts`                       | What is sent, starting suggestions, page names, when "Need help?" may show. Tested.                                                                |

Motion is CSS, the Web Animations API and `requestAnimationFrame` only (no `motion-v`, which stays
off the senior screen and `AppLayout`). The eyes move by setting `translate` on their elements each
frame, with no re-render, and the frames stop once the eyes settle.

## Other languages

Care+ itself is in English, but people may ask Kaki in Chinese, Malay, Tamil or Singlish.

- **Safety checks work in all four.** The emergency and medicine checks (`safety_reply`) have word
  lists for English (with Singlish such as "fall down liao" or "kena fall"), Chinese (Simplified
  and Traditional), Malay and Tamil (`_EMERGENCY_OTHER`, `_MEDICAL_OTHER`). Chinese and Tamil are
  written without spaces between words for `\b` to find, so those words match anywhere in the text.
  An emergency in any of them gets the 995 answer, and a medicine question the "ask a doctor"
  answer, with or without the AI.
- **The fixed answers come in the question's language**, with the English underneath
  (`EMERGENCY_REPLIES`, `MEDICAL_REPLIES`). `language_of` tells the language by its script (Chinese,
  Tamil) or by everyday Malay words; one Singlish word such as "boleh" does not count as Malay.
- **The AI answers in the language it was asked in** (a rule in `INSTRUCTIONS`), keeping button
  and tab names in English as they appear on screen. Its answer is still checked for medicine
  dosing advice in all four languages (`is_dosing_advice`).
- **The built-in helper** (no AI) understands the common questions in all four languages
  (`_INTENTS_OTHER`) but answers in English, and says so first in the question's language. When it
  does not follow a question in another language, it says so and adds "call 995 if it is urgent".
- Voice input still listens for English (`useSpeechInput.ts`, `en-SG`).

## Changing it

- **Name and wording:** `ASSISTANT_NAME` in `useAssistant.ts`; the starting questions in
  `startingSuggestions` (`lib/assistant-chat.ts`); the helper's answers and the AI's instructions
  in `assistant.py` (`GUIDE`, `INSTRUCTIONS`).
- **Page context:** the page name comes from the address (`pageName`). To tell it more about a
  screen, extend the context in `AssistantDock.vue` (`assistant.setContext`) and `AssistantChatRequest`
  in `models.py`, then run `pnpm client:generate`. Keep it to what the person can already see.
- **Draw the eye to something:** `assistantLookAt(x, y)` from `composables/useAssistant.ts` makes
  Kaki glance at a point on the screen for 0.8 s, then go back to the pointer.

## Behaviour to keep

- Enter sends; Shift + Enter is a new line; Send is off while the box is empty or an answer is on
  its way. Escape or the chevron minimises; the conversation is kept until reload or "Clear".
- A press that moves 6 px or more is a drag, not a tap. It stays fully on screen, clear of the
  phone tab bars, and settles against the nearer side when let go within 96 px of it.
- Clicks elsewhere make it glance there: only the position is used, never what was clicked or
  typed.
- "Need help?" shows at most once every 10 minutes, after 25 s on a page, never while the chat is
  open or once it has been used, and never with reduced motion.
- With reduced motion: no eye tracking, blinking, swirl, bounce or growing animation.
