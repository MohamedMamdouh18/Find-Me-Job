#!/bin/sh

if [ ! -f /home/node/.n8n/.imported ]; then
  n8n import:workflow --input=/workflows/ --separate && touch /home/node/.n8n/.imported
fi

exec n8n start