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

# Feedback 5

## Graphs
- Update axis limits if scores shot are outside current limits. Currently vertical lines are plotted outside of visible area of graph
- Show previous passes tick box is not making more lines appear in later passes as it should - is it only plotting from previous matches with the same opponent pairing as the current matches at present? If so change it to show all scores that archer has shot so far, irrespective of which opponent they were against. Label each with pass number
- Remove base handicap from title of score input pages and instead add it to legend for score distributions in graph

## Per Pass Tables
- On score input pages have a single table for just the data that has been entered this pass, not including previous pairings as well. Columns of: Archer | Score | Percentile | Winner. Winner should tisplay yes/no not names as each row relates to an archer. Data from previous passes can be accessed via the per acher results described below.

## Tie breaks
- Percentile, then score if same percentile, then closest to the middle inspected by archers, inputted as a  pair of mutually exclusive tick boxes. This removes the random coin flip currently used in event of ties.

## Advanced mode
- Different target face type/face size/distance shot per archer. All to have drop downs
    - target face type and shape to have all options in `archeryutils`
    - Distances to have same drop down as in simple mode, but specifying per archer

## Outputs
All outputs should be live up to the last completed pass with all results inputted.
- Overall leaderboard across all archers, 1 point for winning a pass, 0 for loosing, draws never happen with above tiebreak logic
- page of per archer results
    - for each archer have a heading of name, total score and handicap, table with columns as below and a row at the bottom of averages for numeric columns.
        - Pass, an integer
        - Opponent, the name of the opponent for that pass
        - Score, score shot in that pass
        - Percentile, percentile in the archer's distribution of that score
        - Handicap, handicap of that score
- Exports to PDF or CSV of all, using sensible formats

## Handicap Calculator
For the standalone tool add a choice of indoor or outdoor round, then display a drop down of all standard indoor/outdoor rounds accounding to the first input. Then the user can input their score and the handicap can be calculated. Keep current choice of specifying if a compound bow was used, only if an indoor round is selected.



# Feedback 6
## Iterations
- Do not display handicap next to archer names during score input. Ignore previous instructions saying to 
- If percentiles are the same for both archers to 1 decimal place then increment decimal places displayed until they are different, unless they are both 100%. 
- Tie break input should only be visible if percentiles and scores tie
- Add a column of per pass handicap to table on score input page
- Have per pass results in /event/results display the data the same way as the tables as on the score input pages, with double or thick horizontal lines between matches so it is clear who was paired with who.
- Exports should have a date time stamp on them
- Exports should have both starting and to-date handicap. To date handicap is caluclated from total score over number of arrows shot so far. This matches final handicap after all arrows are shot.
- Rename start event button on event setup page 2, as now there is an extra step before starting the event.

## Handicap Moving Average
During setup stage 2 if in advanced mode have a yes/no toggle for 'Update Handicaps During Matches'. 
- If no use a constant handicap for per archer probability distribution for all passes.
- If yes for each pass take a weighted average of starting handicap and handicap of arrows shot so far. Parameterise this via $n_{lookback}$, an integer which decides how many $n_{pass}$ arrows back in time to use for calculating handicap at the start of each pass. $n_{lookback} = 1$ uses only the previous $n_{pass}$ to decide the probability distribution for the pass to come. A second integer paramter, _Start Weight_, controls how many $n_{pass}$ arrows the inital handicap counts for, defaulting to $n_{arrows}/n_{pass}$ =5 for 60 arrow round and 12 arrow passes.

# Feedback 7

1. I want the in legend handicap from feedback 5 back.
2. Confirm that if in advanced mode and using moving average handicaps that the distributions per archer that are plotted change between passes
2. When using moving average handicaps all tables that display the per pass handicap (handicap of arrows shot that pass)should display also the per pass starting handicap (used to generate the distribution the score is evaluated against)
3. default n_lookback should be 4, such that for the final pass of a 60 arrow round the score distribution is based only on the arrows shot so far in this round

# Future Plans - DO NOT IMPLEMENT YET

## UI and Deployment
- Nicer UI
    - Using UI library

## Deployment
- Publication to existing webpage/githubpages

## Additional Features
### Maths Explanations
Both to use graphs where appropriate
- Simple
    - High level, accessible explanation of underlying concepts
    - No equations
    - What a handicap is and why it is useful
- Complex
    - Full derivation with equations and justifcations
    - Acknowledge limitations
        - Key limitation: unsure if differnet bowstyles shooting at same handicap level have different variations in score per pass.

### Help
- Toggle to show help on each page where the user inputs stuff
- Explanations of what inputs mean

### Single match mode
System currently setup to run a round robin system of matches. add a single match mode for jsut two people partipating who want a one of match.
- Compound or set system
- Only two archers
- Option to rematch with rolling updated handicaps

### Teams
- Set to team or individual in stage 1 setup. System currently built for individuals.
- if team:
    - configure how many archers and how many arrows
    - pass score distribution needs to be computed from each archer
    - Rename archer to team in other pages

### Feature request form
- For archers to request features

## Licensing and Copyright
- Implement both

# Notes - IGNORE
- Check if differnet bowstyles have different variations in per pass score for the same handicap.

If (and only if) tool becomes popular then think about moving to login system with accounts, history, and per arrow scoring.