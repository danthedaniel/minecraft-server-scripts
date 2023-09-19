#!/bin/bash

tmux send-keys -t minecraft 'stop' Enter

# Wait for Minecraft to terminate
while pgrep -u minecraft java > /dev/null; do
	sleep 1
done
