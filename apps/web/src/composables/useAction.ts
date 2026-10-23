import { ref } from 'vue';

import { classifyApiError } from '@/lib/api-errors';

/**
 * Runs an API call for a screen: `busy` while it is in flight, and any failure turned into plain
 * words in `error` (never a stack trace or a raw status). Resolves true when the call succeeded.
 */
export function useAction() {
  const busy = ref(false);
  const error = ref<string | null>(null);

  async function run(work: () => Promise<void>): Promise<boolean> {
    busy.value = true;
    error.value = null;
    try {
      await work();
      return true;
    } catch (caught) {
      error.value = classifyApiError(caught).message;
      return false;
    } finally {
      busy.value = false;
    }
  }

  return { busy, error, run };
}
