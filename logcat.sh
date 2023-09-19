#!/bin/bash

cd "$( dirname -- "$0" )/../logs"
cat <(zcat *.gz) latest.log
