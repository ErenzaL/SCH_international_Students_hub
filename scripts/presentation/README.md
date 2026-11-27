# Presentation deck generator

`build_deck.js` builds `docs/presentation/SCH-Hub-final-presentation-ko.pptx` (Korean, 21 slides, native charts, speaker
notes) from the numbers in the reports and the screenshots in `docs/presentation/screenshots/` (live public pages, 2026-11-28).

    npm install pptxgenjs@3                      # in a scratch folder, not in the app
    APPLY_THEME=/path/to/apply_theme.js BROWSER_RESULT="114 / 115" node build_deck.js out.pptx

`apply_theme.js` (writes the theme colours into the file) comes with the pptx skill used to build the deck. Every number on
the slides comes from `docs/research/` and `scripts/benchmarks/results/`; update them there first.
