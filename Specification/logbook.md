# Logbook
For AI agents to note their work

# Assumtions

The following assumptions were made when turning `Specification/humanSpec.md` into
`AISpec.md` / `prd.json`, since they were not fully specified by the human spec:

1. Default round is a Portsmouth (60 arrows) rather than a WA18; a round-selection
   control is a reasonable future enhancement but not required for v1.
2. Handicap scheme fixed to `"AGB"` (2023 scheme) rather than `"AGBold"`/`"AA"`/`"AA2"`.
3. `n_pass` is restricted to exact divisors of 60 (`1,2,3,4,5,6,10,12,15,20,30,60`), so
   every pass is the same length and the round divides evenly. Default `n_pass = 12`.
4. Archers are paired strictly in entry order (1v2, 3v4, ...); no bracket/re-pairing UI.
5. Overall match tie-break: majority of passes wins; an even split is shown as a draw,
   with no further tie-break (e.g. sudden-death pass) implemented.
6. Pass-winner tie-break (equal percentile) is: compare raw scores, then coin flip.
7. All match state is in-memory only; no database, no persistence across restarts.
8. Charting (advanced mode) uses `matplotlib` static images rather than a JS charting
   library, to minimise dependencies for a local single-user tool.
9. Bowstyle is collected for display/record-keeping only and never enters any
   calculation, per the explicit exclusion of the bowstyle-variance correction in
   `Specification/humanSpec.md`.

# Implementation History