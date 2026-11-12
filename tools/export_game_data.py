#!/usr/bin/env python3
"""Extracts the data tables the engines need (item definitions, tags, blinds, cards) from
data/game.lua into data/game_data.json.

game.lua is part of Balatro and is not included in this repository. To refresh the data after a
game update, copy game.lua out of your own copy of the game (Balatro.exe is a zip archive; on
macOS it is Balatro.love inside the app bundle) into data/, then run this script."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
from engine import GameData

if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', 'game.lua')
    if not os.path.exists(src):
        sys.exit(f"{src} not found - copy game.lua from your Balatro install into data/")
    out = os.path.join(ROOT, 'data', 'game_data.json')
    s = json.dumps(GameData(src).export(), indent=1, sort_keys=False)
    open(out, 'w', encoding='utf-8').write(s + '\n')
    print('wrote', out, len(s), 'bytes')
