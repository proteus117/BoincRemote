#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"

PROJECT_URL="https://www.primegrid.com/"
SSH_PORT=22
REMOTE_HOST=""
SSH_KEY_PATH=""
WEAK_KEY=""
NO_INSTALL=0

usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --host user@server [options]

Required:
  --host, -H        Remote host in ssh format (for example: user@192.168.1.10)
  --ssh-key, -i     SSH private key path (for example: /home/user/.ssh/id_rsa)

Options:
  --weak-key, -k    Project weak account key (if omitted, prompted securely)
  --project-url, -p Project URL (default: $PROJECT_URL)
  --ssh-port, -P    SSH port (default: $SSH_PORT)
  --no-install      Skip package installation (boinc + GPU dependencies)
  --help            Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host|-H)
      REMOTE_HOST="${2:-}"
      shift 2
      ;;
    --ssh-key|-i)
      SSH_KEY_PATH="${2:-}"
      shift 2
      ;;
    --weak-key|-k)
      WEAK_KEY="${2:-}"
      shift 2
      ;;
    --project-url|-p)
      PROJECT_URL="${2:-}"
      shift 2
      ;;
    --ssh-port|-P)
      SSH_PORT="${2:-}"
      shift 2
      ;;
    --no-install)
      NO_INSTALL=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$REMOTE_HOST" ]]; then
  echo "--host is required." >&2
  usage >&2
  exit 1
fi

if [[ -z "$SSH_KEY_PATH" ]]; then
  echo "--ssh-key is required." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "$SSH_KEY_PATH" ]]; then
  echo "SSH key file not found: $SSH_KEY_PATH" >&2
  exit 1
fi

if [[ ! -r "$SSH_KEY_PATH" ]]; then
  echo "SSH key file is not readable: $SSH_KEY_PATH" >&2
  exit 1
fi

if [[ -z "$WEAK_KEY" ]]; then
  read -r -s -p "Enter weak account key for $PROJECT_URL: " WEAK_KEY
  echo
fi

if [[ -z "$WEAK_KEY" ]]; then
  echo "Weak account key cannot be empty." >&2
  exit 1
fi

# app_config xml file that is written by the program
APP_CONFIG_XML="$(cat <<'XML'
<app_config>
   <app>
      <name>pps_sr2sieve</name>
      <fraction_done_exact/>
   </app>
   <app_version>
       <app_name>pps_sr2sieve</app_name>
       <plan_class>cudaPPSsieve</plan_class>
       <avg_ncpus>.01</avg_ncpus>
       <ngpus>.18</ngpus>
   </app_version>
       <app>
           <name>genefer15</name>
           <fraction_done_exact>1</fraction_done_exact>
           <report_results_immediately>1</report_results_immediately>
       </app>
       <app_version>
           <app_name>genefer15</app_name>
           <plan_class>OCLcudaGFN15</plan_class>
           <ngpus>0.18</ngpus>
           <ncpus>.1</ncpus>
       </app_version>
       <app>
           <name>genefer16</name>
           <fraction_done_exact>1</fraction_done_exact>
           <report_results_immediately>1</report_results_immediately>
       </app>
       <app_version>
           <app_name>genefer16</app_name>
           <plan_class>OCLcudaGFN16</plan_class>
           <ngpus>0.33</ngpus>
           <ncpus>.1</ncpus>
       </app_version>
      <app>
           <name>genefer17mega</name>
           <fraction_done_exact>1</fraction_done_exact>
           <report_results_immediately>1</report_results_immediately>
       </app>
       <app_version>
           <app_name>genefer17mega</app_name>
           <plan_class>OCLcudaGFN17MEGA</plan_class>
           <ngpus>0.33</ngpus>
           <ncpus>.1</ncpus>
       </app_version>
         <app>
           <name>genefer18</name>
           <fraction_done_exact>1</fraction_done_exact>
           <report_results_immediately>1</report_results_immediately>
       </app>
       <app_version>
           <app_name>genefer18</app_name>
           <plan_class>OCLcudaGFN18</plan_class>
           <ngpus>0.5</ngpus>
           <ncpus>.1</ncpus>
       </app_version>
         <app>
           <name>ap26</name>
           <fraction_done_exact>1</fraction_done_exact>
           <report_results_immediately>1</report_results_immediately>
       </app>
       <app_version>
           <app_name>ap26</app_name>
           <plan_class>OCL_cuda_AP27</plan_class>
           <ngpus>.33</ngpus>
           <ncpus>.1</ncpus>
       </app_version>
</app_config>
XML
)"

APP_CONFIG_B64="$(printf '%s\n' "$APP_CONFIG_XML" | base64 | tr -d '\n')"

REMOTE_SCRIPT="$(cat <<'REMOTE_SCRIPT_EOF'
set -euo pipefail

PROJECT_URL="$1"
WEAK_KEY="$2"
APP_CONFIG_B64="$3"
NO_INSTALL="$4"
SERVICE_NAME="boinc-client"

PROJECT_HOST="$(printf '%s' "$PROJECT_URL" | sed -E 's~^https?://~~; s~/.*$~~')"
APP_CONFIG_DIR="/var/lib/boinc-client/projects/$PROJECT_HOST"
APP_CONFIG_PATH="$APP_CONFIG_DIR/app_config.xml"

boincmd() {
  if id -u boinc >/dev/null 2>&1; then
    sudo -u boinc boinccmd "$@"
  else
    sudo boinccmd "$@"
  fi
}

generate_magicdns_style_name() {
  local adjectives nouns
  adjectives=(
    Amber Brave Calm Clever Cobalt Cosmic Crimson Crystal Daring Ember Feral
    Golden Granite Lunar Misty Nimbus Nova Rapid Scarlet Silent Solar Swift
    Velvet Wild
  )
  nouns=(
    Atlas Badger Beacon Cedar Comet Falcon Fjord Harbor Lynx Maple Meteor
    Nimbus Ocean Orion Otter Phoenix River Shadow Summit Tiger Vector Wolf
    Yukon Zenith
  )
  printf '%s%s' \
    "${adjectives[RANDOM % ${#adjectives[@]}]}" \
    "${nouns[RANDOM % ${#nouns[@]}]}"
}

set_boinc_hostname() {
  local new_name="$1"
  if command -v hostnamectl >/dev/null 2>&1; then
    sudo hostnamectl set-hostname "$new_name"
  else
    sudo hostname "$new_name"
  fi
  boincmd --reset_host_info || true
}

NVIDIA_REBOOT_REQUIRED=0
NVIDIA_DEP_STATUS="unknown"
PKG_MGR=""

detect_pkg_mgr() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
  elif command -v dnf >/dev/null 2>&1; then
    echo "dnf"
  elif command -v yum >/dev/null 2>&1; then
    echo "yum"
  else
    echo ""
  fi
}

pkg_refresh() {
  case "$PKG_MGR" in
    apt)
      sudo apt-get update
      ;;
    dnf)
      sudo dnf makecache
      ;;
    yum)
      sudo yum makecache
      ;;
  esac
}

pkg_install() {
  case "$PKG_MGR" in
    apt)
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
      ;;
    dnf)
      sudo dnf install -y "$@"
      ;;
    yum)
      sudo yum install -y "$@"
      ;;
    *)
      echo "Unsupported package manager." >&2
      return 1
      ;;
  esac
}

pkg_is_installed() {
  local pkg="$1"
  case "$PKG_MGR" in
    apt)
      dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -Fq "install ok installed"
      ;;
    dnf|yum)
      rpm -q "$pkg" >/dev/null 2>&1
      ;;
    *)
      return 1
      ;;
  esac
}

has_nvidia_pci() {
  grep -l '^0x10de$' /sys/bus/pci/devices/*/vendor >/dev/null 2>&1
}

nvidia_gpu_visible() {
  local out
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    return 1
  fi
  out="$(nvidia-smi -L 2>&1 || true)"
  if [[ -z "$out" ]]; then
    return 1
  fi
  if grep -qiE 'No devices found|Failed to initialize NVML' <<<"$out"; then
    return 1
  fi
  grep -qiE '^GPU [0-9]+:' <<<"$out"
}

detect_nvidia_branch() {
  dpkg -l 2>/dev/null \
    | awk '/^ii/ {print $2}' \
    | grep -E '^(libnvidia-compute|nvidia-(compute-utils|dkms|kernel-common|utils))-[0-9]+' \
    | sed -nE 's/^.*-([0-9]+)(:.*)?$/\1/p' \
    | head -n1 \
    || true
}

choose_open_driver_pkg() {
  local branch pkg
  branch="$(detect_nvidia_branch)"
  if [[ -n "$branch" ]]; then
    pkg="nvidia-driver-${branch}-open"
    if apt-cache show "$pkg" >/dev/null 2>&1; then
      echo "$pkg"
      return 0
    fi
  fi
  if apt-cache show nvidia-driver-open >/dev/null 2>&1; then
    echo "nvidia-driver-open"
    return 0
  fi
  echo ""
}

unhold_nvidia_packages() {
  local held
  held="$(apt-mark showhold | grep -E '^(libnvidia|nvidia|xserver-xorg-video-nvidia)-[0-9]+' || true)"
  if [[ -n "$held" ]]; then
    # shellcheck disable=SC2086
    sudo apt-mark unhold $held || true
  fi
}

ensure_nvidia_dependencies() {
  local driver_pkg

  if ! has_nvidia_pci; then
    echo "No NVIDIA PCI device detected; skipping CUDA/NVIDIA dependency checks."
    NVIDIA_DEP_STATUS="no_gpu"
    return 0
  fi

  echo "NVIDIA PCI device detected."

  if [[ "$NO_INSTALL" == "1" ]]; then
    echo "--no-install is set; skipping CUDA/NVIDIA package installation."
    if nvidia_gpu_visible; then
      NVIDIA_DEP_STATUS="ready"
    else
      NVIDIA_DEP_STATUS="missing"
    fi
    return 0
  fi

  if [[ "$PKG_MGR" != "apt" ]]; then
    echo "Auto-install for CUDA/NVIDIA dependencies is only implemented for apt-based systems." >&2
    if nvidia_gpu_visible; then
      NVIDIA_DEP_STATUS="ready"
      return 0
    fi
    NVIDIA_DEP_STATUS="missing"
    return 1
  fi

  if pkg_is_installed nvidia-cuda-toolkit; then
    echo "Dependency already present: nvidia-cuda-toolkit"
  else
    echo "Installing missing dependency: nvidia-cuda-toolkit"
    pkg_install nvidia-cuda-toolkit
  fi

  if nvidia_gpu_visible; then
    NVIDIA_DEP_STATUS="ready"
    return 0
  fi

  driver_pkg="$(choose_open_driver_pkg)"
  if [[ -z "$driver_pkg" ]]; then
    echo "Could not determine an installable NVIDIA open-driver package." >&2
    NVIDIA_DEP_STATUS="missing"
    return 1
  fi

  echo "Installing/repairing NVIDIA driver with: $driver_pkg"
  unhold_nvidia_packages
  pkg_install "$driver_pkg"
  NVIDIA_REBOOT_REQUIRED=1

  if nvidia_gpu_visible; then
    NVIDIA_DEP_STATUS="ready"
  else
    NVIDIA_DEP_STATUS="reboot_required"
  fi
}

PKG_MGR="$(detect_pkg_mgr)"
if [[ -z "$PKG_MGR" ]]; then
  echo "Unsupported package manager. Install dependencies manually and rerun with --no-install." >&2
  exit 1
fi

if [[ "$NO_INSTALL" != "1" ]]; then
  pkg_refresh
  pkg_install boinc-client
fi

ensure_nvidia_dependencies

sudo systemctl enable --now "$SERVICE_NAME"

for _ in $(seq 1 30); do
  if boincmd --get_state >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! boincmd --get_state >/dev/null 2>&1; then
  echo "boinccmd could not reach boinc-client after startup." >&2
  exit 1
fi

if boincmd --get_project_status | grep -Fq "master URL: $PROJECT_URL"; then
  echo "Project already attached: $PROJECT_URL"
else
  RANDOM_HOST_LABEL="$(generate_magicdns_style_name)"
  echo "Assigning BOINC host label for new attachment: $RANDOM_HOST_LABEL"
  set_boinc_hostname "$RANDOM_HOST_LABEL"
  boincmd --project_attach "$PROJECT_URL" "$WEAK_KEY"
fi

sudo install -d -m 755 "$APP_CONFIG_DIR"
printf '%s' "$APP_CONFIG_B64" | base64 -d | sudo tee "$APP_CONFIG_PATH" >/dev/null
sudo chmod 644 "$APP_CONFIG_PATH"
if id -u boinc >/dev/null 2>&1; then
  sudo chown boinc:boinc "$APP_CONFIG_PATH"
fi

boincmd --project "$PROJECT_URL" update || true
sudo systemctl restart "$SERVICE_NAME"

echo "BOINC deployment complete."
echo "Attached project: $PROJECT_URL"
echo "Wrote config: $APP_CONFIG_PATH"
if [[ "$NVIDIA_REBOOT_REQUIRED" == "1" || "$NVIDIA_DEP_STATUS" == "reboot_required" ]]; then
  echo "NVIDIA dependencies were installed/updated. Reboot this host to finalize GPU availability."
elif [[ "$NVIDIA_DEP_STATUS" == "ready" ]]; then
  echo "NVIDIA dependency check passed (CUDA + driver visible)."
elif [[ "$NVIDIA_DEP_STATUS" == "missing" ]]; then
  echo "NVIDIA dependency check incomplete; GPU not currently visible to nvidia-smi."
fi
REMOTE_SCRIPT_EOF
)"

echo "Deploying BOINC to $REMOTE_HOST ..."
ssh -T \
  -o BatchMode=yes \
  -o ConnectTimeout=15 \
  -o IdentitiesOnly=yes \
  -i "$SSH_KEY_PATH" \
  -p "$SSH_PORT" \
  "$REMOTE_HOST" \
  "bash -s -- $(printf '%q ' "$PROJECT_URL" "$WEAK_KEY" "$APP_CONFIG_B64" "$NO_INSTALL")" <<<"$REMOTE_SCRIPT"
