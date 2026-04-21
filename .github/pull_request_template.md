## Summary

- what profile or index entry changed
- why the change is needed
- risk tier: low / medium / high

## Validation

- [ ] `python3 scripts/validate_configs.py`
- [ ] `metadata.json` id matches `index.json` profile id
- [ ] `metadata.json` version matches `index.json` version
- [ ] `metadata.json` module_version matches `index.json` module_version
- [ ] `sha256` refreshed after rebuilding zip
- [ ] `generated_at` / `updated_at` / `created_at` are valid ISO 8601 strings

## Device Context

- Tested devices:
- Android versions:
- SoC identifiers:

## Review Notes

- [ ] This change does not remove or rename unrelated packages
- [ ] This change does not break existing `download_url`
- [ ] README included for non-obvious tuning choices
- [ ] Rollback path is clear for this change
