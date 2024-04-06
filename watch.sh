#!/usr/bin/env bash
find profile.yml -type f | entr -r python main.py listen profile.yml