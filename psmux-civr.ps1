# psmux-civr.ps1
# Layout: 2x2 grid — 3x SSH to Pis, 1x local shell


$pis = @(
    "visor@civr-white.local",
    "visor@civr-red.local",
    "visor@civr-blue.local"
    # Add more here as needed, e.g. "visor@civr-green"
)

# Helper: send SSH command (user will be prompted for password)
function Connect-Pi($pane, $target) {
    psmux send-keys -t civr:0.$pane "ssh $target" Enter
}

# Start a new psmux session
psmux new-session -d -s civr

# Create all panes first
psmux split-window -t civr:0.0 -h   # Pane 1 (top-right)
psmux split-window -t civr:0.0 -v   # Pane 2 (bottom-left)
psmux split-window -t civr:0.1 -v   # Pane 3 (bottom-right)

# Even out the pane sizes
psmux select-layout -t civr tiled

# SSH into each Pi
Connect-Pi 0 $pis[0]
Connect-Pi 1 $pis[1]
Connect-Pi 2 $pis[2]
# Pane 3 is left as local shell

# Focus top-left pane
psmux select-pane -t civr:0.0

# Attach to session
psmux attach-session -t civr