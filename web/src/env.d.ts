/**
 * URL of the content-hashed Python bundle relative to the site root (index.html), for example
 * `py/h2h-0123456789ab.zip`. Compiled in at build time by vite.config.ts from
 * scripts/build-py-bundle.mjs, so a deployment always loads its matching bundle.
 */
declare const __PY_BUNDLE__: string;
