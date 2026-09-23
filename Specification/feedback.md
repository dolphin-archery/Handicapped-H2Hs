# Feedback 1 - Base Functionality
- Score input needs error checking and suitable error messages. Score over n_pass arrows cannot be less than zero or greater than n_pass * max score per arrow. hard code max score per arrow to 10 for now. Scores must be integers.
- Display all scores as integers.
- Add to the table handicap of each n_pass arrows shot
- Adapt graphs to be:
    - smooth sharded pdfs for each archer not discretised versions, with everything on one graph
    - A single interactive graph, showing current values of pdfs for each archer when hovering over a given score value
    - Sensible axis limits for the pdfs (full score range does not need to be shown)
    - by default only show vertical lines for most recent n_pass arrows, have a check box to show previous ends as well if desired
- any use of _ to represent subscript should be typset as subscript and not display the _

# Feedback 2
Before implementing any ask me if my intention with these is not clear - they are breif notes.

## Functional
- Rotations to swap pairs of every $n_{pass}$ arrows, to be intialised when event setup
- Indoor/outdoor round toggle, if indoor ensure compounds are using small 10 for handicap calculation

## Two stage setup
### Stage 1
- n_archers integer input
    - If odd number have a toggle for if the bye match should be shot vs sit pass out and have an additional rotation
- total arrows input (default 60)
- n_pass input (default 12)
Output for this stage - pairings initalised for full rotation over total arrows

### Stage 2
- Static convert portmouth/WA 18m full round score to 1 decimal place handicap tool (does not go anywhere, just for ease of use for working out starting handicaps)
- Names
- bowstyles
    - Dropdown for bowstyle in [Recurve, Compound, Barebow]s
- handicaps
- more in advanced mode (see below and bare in mind for code structure for future development, DO NOT IMPLEMENT YET)

## Graphs
- Add toggle to plot all ends not just current

# Future Feedback - DO NOT IMPLEMENT YET

## Advanced mode
- Different scoring method/face/distance per archer. All to have drop downs
    - Scoring method and target face to have all options in `archeryutils`
    - Distances to be input in meters or yards, toggle for which units

## Outputs
- Overall leaderboard across all archers, 1 point for winning a match
- Results print outs

## UI and Deployment
- UI, get existing design from online - may need something more than flask?
- Publication to existing webpage/githubpages

# Notes - IGNORE
- Check if differnet bowstyles have different variations in per pass score for the same handicap.