#!/bin/sh
# openfootball football.json (public domain). Run from the project root.
set -e
mkdir -p data/raw/openfootball && cd data/raw/openfootball
for s in 2023-24 2024-25 2025-26 2026-27; do
  for l in en.1 es.1 fr.1 de.1 it.1; do
    curl -sf -o "${s}_${l}.json" "https://raw.githubusercontent.com/openfootball/football.json/master/$s/$l.json"
  done
done
