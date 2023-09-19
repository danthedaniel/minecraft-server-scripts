#!/bin/bash

if ! [ "$#" -gt 0 ]; then
  echo "Usage: command.sh <...args>"
  exit 1
fi

echo "> $*"
tmux send-keys -t minecraft "$*" Enter
