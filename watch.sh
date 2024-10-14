#!/usr/bin/env bash
find . -name "*.yml" | entr -r python main.py listen profile.yml