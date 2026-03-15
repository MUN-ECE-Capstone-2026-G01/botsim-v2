#!/bin/bash

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <hostname>"
    echo "Example: $0 pi-node-1"
    exit 1
fi

HOSTNAME="$1"

echo "=== Setting hostname to '$HOSTNAME' ==="
sudo hostnamectl set-hostname "$HOSTNAME"

echo "=== Updating /etc/hosts ==="
if grep -q "^127\.0\.1\.1" /etc/hosts; then
    sudo sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts
else
    echo -e "127.0.1.1\t$HOSTNAME" | sudo tee -a /etc/hosts
fi

echo "=== Ensuring avahi-daemon is enabled and running ==="
sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon

echo ""
echo "Done! This Pi is now reachable at: $HOSTNAME.local"
echo "Reboot recommended for all changes to take full effect."
