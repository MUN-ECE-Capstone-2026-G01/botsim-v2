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

echo "=== Ensuring SSH server is enabled and running ==="
sudo systemctl enable ssh
sudo systemctl start ssh

echo "=== Ensuring avahi-daemon is installed ==="
if ! dpkg -s avahi-daemon &>/dev/null; then
    echo "avahi-daemon not found, installing..."
    sudo apt-get install -y avahi-daemon
fi

echo "=== Configuring avahi to use wlan0 only (prevents hostname conflict from multiple interfaces) ==="
sudo sed -i 's/^#*allow-interfaces=.*/allow-interfaces=wlan0/' /etc/avahi/avahi-daemon.conf
# If the line doesn't exist at all, add it under [server]
if ! grep -q "^allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
    sudo sed -i '/^\[server\]/a allow-interfaces=wlan0' /etc/avahi/avahi-daemon.conf
fi

sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon

echo ""
echo "Done! This Pi is now reachable at: $HOSTNAME.local"
echo "Reboot recommended for all changes to take full effect."
