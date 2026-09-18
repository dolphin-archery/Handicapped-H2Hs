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

# Future Feedback - DO NOT IMPLEMENT YET
## Functional
- n_archers input
- Accounting for different variation in per pass score between different bowstyles. 
    - map distribution score inputs to numeric classifications and compare percentiles of these? Or use a fudge factor?
- Bowstyle dropdown
- Different faces/distances (default same for all, option to change for each)
- Rotations for group of archers

## Graphs
- Keep current score one
- Add handicap one as well (toggle)

## Outputs
- Overall scoring system for groups of archers
- Results print outs

## UI and Deployment
- UI, get existing design from online - may need something more than flask?
- Publication to existing webpage/githubpages