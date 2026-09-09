# Handicapped-H2Hs
Code for fair handicapped H2Hs in archery utilising the Archery GB handicap system as implemented by [Jack Atkinson](https://github.com/jatkinson1000/archeryutils/tree/main)

# General Notes
- Develop a prior distribution of probability of shooting a given score $S$ as a function bowstyle $B \in {R, C, B, L}$ given a existing handicap for an archer.
- Use this distribution either via standardisation or $p$ values to fairly compare two archers when competining in a H2H.
    - This allows for not only the comparison of differnet average skill levels (as adding a score allowance to each archer does), but also for the different variation in scores over an end/dozen achieved by different skill levels/bowstyles.