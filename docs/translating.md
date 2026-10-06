# Translating the dashboard

Every word the dashboard shows lives in one table,
[`agent/web/js/strings.js`](../agent/web/js/strings.js). Each entry has two
versions: **Simple** (everyday words, the default) and **Technical** (the
precise terms). English is the table itself, and it is the fallback for
every other language.

## Adding a language

1. Make `agent/web/lang/<code>.json`, for example `agent/web/lang/de.json`.
   The code is two lowercase letters, optionally followed by a region
   (`pt-BR`).
2. Copy the entries you want to translate from the table, with the same
   keys, and translate both versions:

   ```json
   {
     "action.start": ["Starten", "Starten"],
     "head.players.one": ["{count} Spieler online", "{count} Spieler online"]
   }
   ```

3. Keep every `{placeholder}` exactly as it is in English. The test suite
   checks this.

A file can hold only some of the entries: any key it leaves out, or gets
wrong, is shown in English. So a half-done translation is still usable.

The dashboard loads a language with `loadLanguage(code)` from `strings.js`.
Choosing a language from App settings is not built yet; until it is, a
language file is used only by code that calls `loadLanguage`.

## Checks

`tests/test_strings.py` reads every file in `agent/web/lang/` and fails if a
key is not in the English table, if an entry is not a `[Simple, Technical]`
pair, or if a placeholder differs from English.
