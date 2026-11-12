#!/usr/bin/env python3
"""Differential test: Python engine (engine.py) vs C core (core.h) on random seeds AND random option combinations.
Both implementations must emit exactly the same event stream.   python difftest.py [n_cases] [antes]"""
import random, subprocess, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repository root
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Run, load_data, SEED_CHARS
from bridge import build_cfg, events, item_index

D = load_data()
HERE = os.path.join(ROOT, 'src')
VOUCHERS = ['v_overstock_norm', 'v_overstock_plus', 'v_tarot_merchant', 'v_tarot_tycoon', 'v_planet_merchant', 'v_planet_tycoon',
            'v_magic_trick', 'v_illusion', 'v_hone', 'v_glow_up', 'v_crystal_ball', 'v_omen_globe', 'v_telescope', 'v_observatory']
HANDS = ['High Card', 'Pair', 'Flush', 'Straight', 'Full House', 'Two Pair', 'Three of a Kind']
JOKERS = [k for k, v in D.centers.items() if v['set'] == 'Joker' and v['rarity'] in (1, 2)]

def random_opts(rnd, antes, plain=False):
    if plain:
        return {}
    o = {}
    o['deck'] = rnd.choice(['b_red'] * 4 + ['b_ghost', 'b_magic', 'b_nebula', 'b_zodiac', 'b_black', 'b_painted'])
    o['unlocked'] = rnd.choice(['all', 'all', 'fresh'])
    o['planets_played'] = rnd.random() < 0.2
    o['take_souls'] = rnd.random() < 0.85
    o['start_consumables'] = rnd.choice(['held', 'used'])
    if rnd.random() < 0.4: o['most_played'] = rnd.choice(HANDS)
    o['skips'] = {f"{g}{k}" for g in range(1, antes + 1) for k in 'sb' if rnd.random() < 0.25}
    o['rerolls'] = {f"{g}{k}": rnd.randint(1, 3) for g in range(1, antes + 1) for k in 'sbx' if rnd.random() < 0.2}
    sp = {f"{g}{k}.{j}" for g in range(1, antes + 1) for k in 'sbx' for j in (1, 2) if rnd.random() < 0.15}
    if rnd.random() < 0.3: sp.add('tagpack:' + rnd.choice(['tag_charm', 'tag_buffoon', 'tag_meteor', 'tag_ethereal', 'tag_standard']))
    o['skip_packs'] = sp
    o['buy_vouchers'] = rnd.sample(VOUCHERS, rnd.randint(0, 6))
    o['take'] = rnd.sample(JOKERS, rnd.randint(0, 25)) + (['j_ring_master'] if rnd.random() < 0.2 else []) + \
                (rnd.sample(['c_fool', 'c_hermit', 'c_jupiter'], 1) if rnd.random() < 0.3 else [])
    o['own'] = rnd.sample(JOKERS, rnd.randint(0, 2)) + (['j_ring_master'] if rnd.random() < 0.1 else [])
    o['locked'] = rnd.sample(JOKERS, rnd.randint(0, 10))
    return o

def run_case(seed, antes, o, rr):
    exe = os.path.join(HERE, 'bsearch')
    cfg = build_cfg(D, o)
    cmd = [exe, '--trace', seed, '--antes', str(antes), '--cfg', ','.join(map(str, cfg))]
    if rr:
        cmd += ['--crit', f"0,-1,1,8,0,0,0,0,{rr},-1,-1"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.split('\n')
    c_ev = [tuple(int(x) for x in ln.split()[1:]) for ln in out if ln.startswith('E ')]
    oo = dict(o); oo['preview_rerolls'] = rr
    T = Run(seed, D, **oo).simulate(antes)
    p_ev = [(e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7]) for e in events(D, T)]
    return c_ev, p_ev

def main(n, antes):
    rnd = random.Random(2024)
    names = {v: k for k, v in item_index(D).items()}
    bad = 0
    for t in range(n):
        plain = t < n // 4
        seed = ''.join(rnd.choice(SEED_CHARS) for _ in range(rnd.choice([8, 8, 8, 5, 3])))
        o = random_opts(rnd, antes, plain)
        rr = 0 if plain else rnd.choice([0, 0, 1, 2])
        c_ev, p_ev = run_case(seed, antes, o, rr)
        if c_ev != p_ev:
            bad += 1
            for i, (x, y) in enumerate(zip(c_ev + [None] * 5, p_ev + [None] * 5)):
                if x != y:
                    print(f"MISMATCH seed={seed} case={t} at event {i}/{len(p_ev)}\n  opts={o} rr={rr}")
                    print('  C :', x, names.get(x[4]) if x else '')
                    print('  Py:', y, names.get(y[4]) if y else '')
                    break
            if bad >= 4:
                break
        if (t + 1) % 100 == 0:
            print(f"{t + 1} cases, mismatches {bad}", flush=True)
    print(f"done: {t + 1} cases x {antes} antes, mismatches: {bad}")
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 400, int(sys.argv[2]) if len(sys.argv) > 2 else 4))
