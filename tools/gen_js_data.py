#!/usr/bin/env python3
"""Exports the game data parsed from game.lua (same parser as engine.py) as compact JSON for ui/engine.js."""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repository root
sys.path.insert(0, os.path.join(ROOT, 'src'))
from engine import load_data

def build():
    D = load_data()
    C = {}
    for k, v in D.centers.items():
        c = {'n': v['name'], 's': v['set'], 'o': v['order']}
        if v.get('rarity') is not None: c['r'] = v['rarity']
        if v.get('unlocked') is False: c['u'] = False
        if v.get('requires'): c['rq'] = v['requires']
        if v.get('softlock'): c['sl'] = True
        if v.get('enhancement_gate'): c['eg'] = v['enhancement_gate']
        if v.get('yes_pool_flag'): c['yp'] = v['yes_pool_flag']
        if v.get('kind'): c['k'] = v['kind']
        if v.get('weight') is not None: c['w'] = v['weight']
        if v.get('extra') is not None and v['set'] == 'Booster': c['e'] = v['extra']
        if v.get('choose') is not None and v['set'] == 'Booster': c['c'] = v['choose']
        if v.get('hand_type'): c['h'] = v['hand_type']
        C[k] = c
    data = {
        'centers': C,
        'pool': {s: [v['key'] for v in lst] for s, lst in D.pool.items()},
        'rarity': {str(r): [v['key'] for v in lst] for r, lst in D.rarity_pool.items()},
        'tag_pool': [t['key'] for t in D.tag_pool],
        'tags': {k: {'n': v['name'], 'm': v['min_ante'], 'rq': v['requires']} for k, v in D.tags.items()},
        'blinds': {k: {'n': v['name'], 'b': ([v['boss']['min'], v['boss']['max'], 1 if v['boss']['showdown'] else 0] if v['boss'] else None)}
                   for k, v in D.blinds.items()},
        'cards': {k: v['name'] for k, v in D.cards.items()},
        'card_keys': D.card_keys_sorted,
    }
    return data

if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'ui', 'data.json')
    s = json.dumps(build(), separators=(',', ':'))
    open(out, 'w').write(s)
    print('wrote', out, len(s), 'bytes')
