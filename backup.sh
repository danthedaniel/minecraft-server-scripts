#!/bin/bash
set -euo pipefail

cd "$( dirname -- "$0" )/.."

function send_command {
    tmux send-keys -t minecraft "$1" Enter
}

function cleanup {
    send_command 'save-on'
    # Delete old backups
    local retention_days='3'
    find backups -name "backup-*.tar.gz" -type f -mtime +"$(expr $retention_days - 1)" -delete
}
trap cleanup EXIT

send_command 'save-all'
sleep 3

send_command 'save-off'
sleep 3

TIMESTAMP=$(date '+%Y%m%d-%H-%M-%S')
tar -czf backups/backup-${TIMESTAMP}.tar.gz world/ world_nether/ world_the_end/
