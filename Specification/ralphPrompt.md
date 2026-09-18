For a number of iterations given as an input parameter:
1. Analyse prd.json and decide which task to work on next. This should be the task you think to be the highest proprity, not the first in the list. Consider the critical path for building downstream components when deciding this.
2. If the selected task is large, break it down into smaller sub tasks and complete each sequentially. Use subagents where necessary.
3. Check any feedback loops, such as tests, and verify your solution meets that defined in prd.json
4. Comment on your progress giving a brief summary of changes, any issues and notes for future development in logbook.md. Also update the passes flag for that item in prd.json if it is complete.
5. Make a git commit of this feature with a descriptive name
6. if while working on this all items in prd.json have a passes flag of true, exit the loop and inform me the task is complete.
