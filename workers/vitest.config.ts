import { defineWorkersConfig } from '@cloudflare/vitest-pool-workers/config';

// Entirely local; deliberately do not load production bindings or secrets.
export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        miniflare: {
          compatibilityDate: '2025-09-06',
          compatibilityFlags: ['nodejs_compat'],
          d1Databases: ['DB'],
          bindings: { SCHOOL_API_TOKEN: 'local-test-only', APP_VERSION: 'test' },
        },
      },
    },
  },
});
