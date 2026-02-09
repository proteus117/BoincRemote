# BoincRemote

This directory contains two programs:

- `boinc_remote_deploy.sh`: deploy/configure BOINC on a remote headless machine.
- `boinc_tasktop.py`: terminal dashboard (htop-style) for BOINC task monitoring.

## `boinc_remote_deploy.sh`

### What it does

The deployment script connects to a remote server over SSH and:

1. Installs `boinc-client` (unless `--no-install` is used).
2. Checks NVIDIA/CUDA dependencies (apt systems):
   - installs `nvidia-cuda-toolkit` if missing.
   - attempts to install an NVIDIA open driver package when GPU exists but is not visible.
3. For new project attachments, assigns a random two-word host label (MagicDNS-style CamelCase).
4. Attaches BOINC to a project (default: PrimeGrid) using a weak account key.
5. Writes `app_config.xml` to:
   - `/var/lib/boinc-client/projects/<project-host>/app_config.xml`
6. Restarts `boinc-client`.

### Usage

```bash
./boinc_remote_deploy.sh --host user@server --ssh-key /path/to/private_key [options]
```

### Required arguments

| Argument | Description |
|---|---|
| `--host`, `-H` | Remote host in SSH form (example: `root@203.0.113.10`). |
| `--ssh-key`, `-i` | SSH private key path used for remote access. |

### Optional arguments

| Argument | Default | Description |
|---|---:|---|
| `--weak-key`, `-k` | prompt | BOINC project weak account key. |
| `--project-url`, `-p` | `https://www.primegrid.com/` | BOINC project URL to attach. |
| `--ssh-port`, `-P` | `22` | SSH port for remote host. |
| `--no-install` | off | Skip package installs (`boinc-client` and GPU dependencies). |
| `--help`, `-h` | n/a | Show help. |

### Examples

Deploy to PrimeGrid on a custom SSH port:

```bash
./boinc_remote_deploy.sh \
  --host root@203.0.113.10 \
  --ssh-port 2222 \
  --ssh-key /home/youruser/.ssh/id_rsa \
  --weak-key "YOUR_WEAK_KEY"
```

Run config/attach only (skip package installation):

```bash
./boinc_remote_deploy.sh \
  --host root@203.0.113.10 \
  --ssh-port 2222 \
  --ssh-key /home/youruser/.ssh/id_rsa \
  --weak-key "YOUR_WEAK_KEY" \
  --no-install
```

### Notes

- If GPU driver packages are changed, script may print:
  - `NVIDIA dependencies were installed/updated. Reboot this host to finalize GPU availability.`
- The script uses non-interactive SSH (`BatchMode=yes`), so key-based auth must already work.

## `boinc_tasktop.py`

### What it does

`boinc_tasktop.py` is a terminal dashboard for BOINC tasks. It parses `boinccmd --get_tasks` output and shows:

- task counts (running/total)
- per-task state
- per-task resource usage (CPU/GPU)
- fraction done and ETA
- aggregate running CPU/GPU totals

### Usage

Interactive dashboard:

```bash
./boinc_tasktop.py [options]
```

One-shot snapshot (prints once, exits):

```bash
./boinc_tasktop.py --once [options]
```

### Arguments

| Argument | Default | Description |
|---|---:|---|
| `--boinccmd` | `boinccmd` | Command used to run BOINC CLI. Can be a wrapped command string (including SSH). |
| `--interval` | `2.0` | Refresh interval in seconds (`>= 0.5`). |
| `--all` | off | Start in all-tasks mode (default is running tasks only). |
| `--once` | off | Print one snapshot and exit. |
| `--no-sudo-fallback` | off | Disable fallback command `sudo -n -u boinc boinccmd --get_tasks`. |

### Interactive keys

| Key | Action |
|---|---|
| `q` | Quit |
| `a` | Toggle running-only / all tasks |
| `r` | Refresh immediately |
| `+` / `-` | Increase/decrease refresh interval |
| `Arrow Up/Down` or `k`/`j` | Scroll |
| `PageUp/PageDown` | Scroll faster |

### Examples

Run locally on a host where `boinccmd` is available:

```bash
./boinc_tasktop.py
```

Query remote BOINC over SSH from local machine:

```bash
./boinc_tasktop.py --once --all \
  --boinccmd "ssh -o BatchMode=yes -o ConnectTimeout=20 -o IdentitiesOnly=yes -i /home/youruser/.ssh/id_rsa -p 2222 root@203.0.113.10 boinccmd"
```
