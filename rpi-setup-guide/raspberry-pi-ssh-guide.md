# Connecting to Multiple Raspberry Pis from Windows over WiFi

This guide explains how to SSH into multiple Raspberry Pis by hostname (e.g. `pi-node-1.local`) from a Windows machine, even when switching between different WiFi networks.

---

## Overview

Rather than using fixed IP addresses (which change between networks), we use **mDNS hostnames** so you can always SSH with `ssh user@pi-node-1.local` regardless of which network you're on.

---

## Step 1: Set a Unique Hostname on Each Raspberry Pi

On each Pi, set a unique hostname:

```bash
sudo hostnamectl set-hostname pi-node-1
```

Use a different name for each Pi (e.g. `pi-node-2`, `pi-node-3`, etc.).

---

## Step 2: Update `/etc/hosts` on the Pi

When you change the hostname, the `/etc/hosts` file doesn't update automatically. If it still has the old hostname, mDNS won't advertise the new name correctly.

Open the file:

```bash
sudo nano /etc/hosts
```

Find the line with `127.0.1.1` and update it to match the new hostname:

```
127.0.1.1   pi-node-1
```

Save with `Ctrl+X`, then `Y`, then `Enter`.

---

## Step 3: Make Sure avahi-daemon is Running on the Pi

`avahi-daemon` is what broadcasts the `.local` hostname on the network. Check its status:

```bash
sudo systemctl status avahi-daemon
```

If it's not running, enable and start it:

```bash
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon
```

After updating `/etc/hosts`, restart it to pick up the new hostname:

```bash
sudo systemctl restart avahi-daemon
```

---

## Step 4: Install Bonjour on Windows

Windows doesn't reliably resolve `.local` hostnames without Bonjour. 

1. Search for **"Bonjour Print Services for Windows"** on Apple's website
2. Download and install it
3. Restart your terminal (PowerShell or Command Prompt)

Verify the service is running by opening **Services** (`Win + R` → `services.msc`) and checking that **Bonjour Service** is started.

---

## Step 5: SSH from Windows

Open PowerShell or Command Prompt and connect:

```powershell
ssh visor@pi-node-1.local
```

You can also use PuTTY — just enter `pi-node-1.local` as the hostname.

---

## Troubleshooting

**Ping to verify resolution before SSH:**
```powershell
ping pi-node-1.local
```

**Check Bonjour can discover the Pi:**
```powershell
dns-sd -B _ssh._tcp
```
Your Pi should appear in the list. If it doesn't, re-check Steps 2 and 3.

**If all else fails, find the current IP on the Pi:**
```bash
hostname -I
```
Then SSH directly by IP while you debug the hostname issue:
```powershell
ssh visor@192.168.x.x
```

---

## Notes

- This setup works across different WiFi networks — as long as all devices are on the **same network at the same time**, `.local` hostnames will resolve automatically
- You do **not** need static IP addresses for this approach
- Repeat Steps 1–3 for every Raspberry Pi, using a unique hostname each time
