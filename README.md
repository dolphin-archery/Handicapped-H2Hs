# Handicapped-H2Hs
Code for fair handicapped H2Hs in archery utilising the Archery GB handicap system as implemented by [Jack Atkinson](https://github.com/jatkinson1000/archeryutils/tree/main)

# General Notes
- Develop a prior distribution of probability of shooting a given score (handicap over $n_{pass}$ arrows) $S$ as a function bowstyle $B \in {R, C, B, L}$ given a existing handicap, $h_i$ for an archer.
- Use this distribution either via standardisation or $p$ values to fairly compare two archers when competining in a H2H.
    - This allows for not only the comparison of differnet average skill levels (as adding a score allowance to each archer does), but also for the different variation in scores over an end/dozen achieved by different skill levels/bowstyles.

# To Get Prior Distribution
## Method 1 - Existing Data
To do this need a lot of per arrow data for relevant indoor rounds across all $B$ and $h$. 
- Scrape lots of data (AGB Scores Server?)
- For a given handicap and bostyle, have small buffer either side in handicap. Find all rounds in that buffer and plot arrow score distribution.
- Fit a parametric distribution to this and save parameters
- Repeat over all $b$ and range of $h$
    - use classifications to inform discritisation of $h$?
- Make smooth functions of parameters over $h$ for each $B$
- This forms the prior distribution of per arrow scores
- Use monte carlo simulation to find scores over $n_pass$ arrows.
- The forms the distribution needed for fair comparisons

## Method 2 - Classifications
Instead of using $p$ values or $z$ scores to decide the winner, instead compute the numeric equivalent classification (IA3 = 0, IGMB = 8) for handicap of previous round. Then for each $n_{pass}$ arrows shot find the classification of this, and then express their score as the difference of these numeric classifications. The classifications have already been fitted to large number of tounrnament results so should account for the greater variability between bowstyle already. If they account for variation in per $n_{pass}$ arrows sufficiently robustly remains to be seen.