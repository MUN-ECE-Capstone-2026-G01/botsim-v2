# Test Plan

To test (step 1.6):

1. Copy `robot/` to the Pi: `rsync -r robot/ visor@civr-1.local:~/botsim/robot/`

2. Copy the new deck.sh to the Pi, replacing the existing one: `scp deck.sh visor@civr-1.local:~/deck.sh`

3. SSH in and run ~/deck.sh — robot should behave identically to before (drives to (0, 1))
