#!/bin/bash

tmux send-keys -t minecraft 'say Restarting server in 15 seconds...' Enter
sleep 15
sudo systemctl restart minecraft
