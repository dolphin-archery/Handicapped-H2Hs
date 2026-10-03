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

# Feedback 3

## Iteration from Feedback 1
- Handicap calculator needs to know if round shot with a compound bow or not
- add longbow to bowstyle drop down
- switch back to preious page strucutre with one page per match that you click into for entering results, shows graphs/results so far per match there, then go back to summary of all current matches. I do not like the current view of inputting data for all matches at once. Add a button to move forward to the next pass once all data from a given pass has been entered. This should update the pairings in the overview page and allow data for the next pass to be entered on the per match pages.
- I do not think the bye features was implemented as I intended. If an odd number of archers $n$ are entered there should be an option to 'Shoot Byes?'. If set to yes then all archers shoot in every pass, with each archer having one match with no opponent. If set to no then archers with byes sit that pass out and only shoot matches with opponents. This will change the total number of passes it takes to shoot the full round.

# Feedback 4
- Display handicap of each archer in per match pages
- add a stage 3 of event setup where pairing assignment is done
    - Option to redraw the random assignment of pairings by pressing a button
- Confirmation button before resetting scores
- Rename current advance mode to graph view. A different advanced mode will be added soon. Only display button on score input pages, not summary pages.
- Fix bug that hovering over graph to see per archer probailities for a given score breaks for vertical lines of scores shot in previous pass.
- Add a toggle for simple or advanced mode on first setup page. 
    - Simple mode sets all archers to the same distance and target faces size. There should be drop downs for both distance and face size if simple mode is selected, with options for the standard metric/imperial distances and face sizes. Face type should be the standard archery face (not 3 spots), though compound archers take care to ensure compound archers still have the reduced size 10. Indoor/outdoor arrow diameter size should be inferred from the distance and the corresponding arrow diamter used in handicap calculations. (I think all distances >30m class as outdoor though check this as I am not certain)
    - Advanced mode will be implemeted later. Leave a TBA message for now.
- Validate that starting handicaps are in the allowed range of handicap values (0-150)
- Simplify how the winner is decided text that shows on the bottom of score input pages
- Update summary table per pass (/event/rotation) to have columns of Match | Score | Percentiles | Winner | Actions
    - Match is as it currently is, showing opponents
    - Score should be  A - B where A and B are numbers, shown the same way around as opponents in match column
    - Percentiles should be as above but the percentiles in each archer's distribution
    - Winner should be the name of the person who won that pass
    - Actions links to the score input pages, as currently but the table needs the heading.

# Future Plans - DO NOT IMPLEMENT YET

## Advanced mode
- Different scoring method/face/distance per archer. All to have drop downs
    - Scoring method and target face to have all options in `archeryutils`
    - Distances to be input in meters or yards, toggle for which units

## Outputs
- Overall leaderboard across all archers, 1 point for winning a match, 0 for loosing, draws never happen
- Results print out to .pdf and .csv
- page of per archer results
    - for each archer have a heading of name, total score and handicap, table with columns as below and a row at the bottom of averages for numeric columns.
        - Pass, an integer
        - Opponent, the name of the opponent for that pass
        - Score, score shot in that pass
        - Percentile, percentile in the archer's distribution of that score
        - Handicap, handicap of that score



## UI and Deployment
- Nicer UI
    - get existing design from online - may need something more than flask
- Explanation of underlying maths
- Guide for how to use
- Publication to existing webpage/githubpages

# Notes - IGNORE
- Check if differnet bowstyles have different variations in per pass score for the same handicap.