# Preserved predecessor runtime

`runtime.zip` preserves the exact 51 files present before this migration, including uncommitted source changes, scripts, configuration, frozen scenario, documentation and all 170 predecessor tests. `manifest.json` records SHA-256 for every entry. The archive is historical data, outside the Python import and pytest paths; no compatibility adapter loads it.

The predecessor uses a different mission model. Its tests are not evidence for the 2026-09-17 formulation. The generic network geometry module and its two tests remain active unchanged. All other predecessor runtime entry points and model-specific tests were replaced, with scalar/resource, geometric/temporal integration, scope and input-rejection coverage in the new suite. Unrelated historical research documents and presentation artifacts were preserved.
