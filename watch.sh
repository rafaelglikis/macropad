#!/usr/bin/env bash
source venv/bin/activate
find . -name "*.yml" | entr -r python main.py listen prifile/profile.yml