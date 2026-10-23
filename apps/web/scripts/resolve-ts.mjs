// Lets `node --test` run the web's pure TypeScript modules with Node's built-in type stripping and
// no test framework: the app writes relative imports without an extension (the bundler's style),
// which Node's ESM resolver does not guess, so this retries a failed relative import as `.ts`.
// It only resolves extensionless relative `.ts` imports (no `@/` alias, `.tsx` or directory index),
// so view-model modules under test must keep their runtime imports relative.
import { registerHooks } from 'node:module';

registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      if (specifier.startsWith('.') && !/\.[cm]?[jt]sx?$/.test(specifier)) {
        return nextResolve(`${specifier}.ts`, context);
      }
      throw error;
    }
  },
});
