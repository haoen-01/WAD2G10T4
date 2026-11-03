// Type-checks the SPA with vue-tsc. Unused imports and locals are errors: this repo has no ESLint, so
// this is what catches dead code. src/api-client (the API client: a hand-written facade over the
// generated SDK) is type-checked on its own by `tsc -p tsconfig.api-client.json` and must not be
// edited for these app-only rules, so diagnostics located under src/api-client/ are ignored here.
import { spawnSync } from 'node:child_process';

const FLAGS = ['--noEmit', '--noUnusedLocals', '--noUnusedParameters'];
const DIAGNOSTIC = /^(.+?)\(\d+,\d+\): error TS\d+:/;

let failed = false;
for (const project of ['tsconfig.json', 'tsconfig.node.json']) {
  const run = spawnSync('vue-tsc', [...FLAGS, '-p', project], { encoding: 'utf8', shell: true });
  const output = `${run.stdout ?? ''}${run.stderr ?? ''}`;

  // A diagnostic is one line plus any indented continuation lines.
  const diagnostics = [];
  for (const line of output.split(/\r?\n/)) {
    if (DIAGNOSTIC.test(line)) diagnostics.push([line]);
    else if (/^\s/.test(line) && diagnostics.length > 0) diagnostics.at(-1).push(line);
  }
  const ours = diagnostics.filter(
    ([first]) => !first.replaceAll('\\', '/').startsWith('src/api-client/'),
  );

  if (ours.length > 0) {
    console.error(ours.flat().join('\n'));
    failed = true;
  } else if (run.status !== 0 && diagnostics.length === 0) {
    // vue-tsc failed without a diagnostic we can read (crash, missing binary): never pass silently.
    console.error(output || run.error?.message || `vue-tsc exited with ${run.status}`);
    failed = true;
  }
}

process.exit(failed ? 1 : 0);
