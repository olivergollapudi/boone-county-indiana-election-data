# Contributing

Thank you for helping keep this dataset accurate. The most valuable contribution is
**finding a number that doesn't match the Clerk's report**.

## Reporting a data error

Open an issue with the **"Report a data error"** form. It asks for:

- the election, precinct and contest;
- the value in this dataset, and the value you believe is correct;
- where the correct value appears: the PDF in `source_pdfs/` and its page.

Every published number comes from a Clerk PDF in `source_pdfs/`, so a report that names
the page can be checked directly. Confirmed errors are fixed in the scripts (never by
editing a CSV by hand), the pipeline is rerun, and the fix is noted in the release notes.

## Other issues

Use a blank issue for questions, suggestions, or problems with the maps or code. For
questions about method, please read [METHODOLOGY.md](METHODOLOGY.md) first; for column
meanings, [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

## Changing code or data

Pull requests are welcome. A few rules keep the data defensible:

1. **No hand edits to data files.** Change a script in `scripts/`, then regenerate. Every
   number must trace back to a Clerk report through code.
2. **No estimates in the master.** `data/results_long_*.csv` is "what the Clerk reported."
   Anything modeled belongs in `data/normalized/` and must be labeled as such.
3. **All checks must pass.** Run the full rebuild in [README.md](README.md#rebuild-from-source);
   the parser, normalization (`V1`–`V5`), as-drawn (`A1`–`A3`) and site (`W1`–`W3`)
   checks stop the build on any failure.
4. **Nonpartisan presentation.** Spell out party names, use neutral wording, and keep the
   colorblind-checked palette in `scripts/make_maps.py`.
5. **Describe the effect.** In the pull request, say which elections and rows change and
   why.

By contributing, you agree that your code is released under the [MIT License](LICENSE)
and your data or documentation changes under [CC0 1.0](LICENSE-DATA).
