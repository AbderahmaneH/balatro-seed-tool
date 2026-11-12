#!/usr/bin/env python3
"""Differential test: Python engine vs the JavaScript engine (ui/engine.js) on random seeds and option combinations.
Needs node.   python difftest_js.py [n_cases] [antes]"""
import json, os, random, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repository root
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Run, load_data, SEED_CHARS
from bridge import events, item_index
import difftest

HERE = ROOT
D = load_data()
NODE = r"""
const fs = require('fs');
const E = require(process.argv[2])(JSON.parse(fs.readFileSync(process.argv[3], 'utf8')));
const cases = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
const out = cases.map(c => { const r = new E.Run(c.seed, Object.assign({}, c.opts, {preview_rerolls: c.rr})); return E.events(r.simulate(c.antes)); });
fs.writeFileSync(process.argv[5], JSON.stringify(out));
"""

def jsonable(o):
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in o.items()}

def main(n, antes):
    rnd = random.Random(777)
    cases = []
    for t in range(n):
        plain = t < n // 5
        seed = ''.join(rnd.choice(SEED_CHARS) for _ in range(rnd.choice([8, 8, 6, 4, 2, 1])))
        o = difftest.random_opts(rnd, antes, plain)
        stake = rnd.randint(1, 8)
        o['stake'] = stake
        rr = 0 if plain else rnd.choice([0, 0, 1, 2])
        cases.append(dict(seed=seed, opts=jsonable(o), rr=rr, antes=antes, py_opts=o))
    with tempfile.TemporaryDirectory() as d:
        cf, of, sf = (os.path.join(d, x) for x in ('cases.json', 'out.json', 'h.js'))
        json.dump([{k: v for k, v in c.items() if k != 'py_opts'} for c in cases], open(cf, 'w'))
        open(sf, 'w').write(NODE)
        p = subprocess.run(['node', sf, os.path.join(HERE, 'ui', 'engine.js'), os.path.join(HERE, 'ui', 'data.json'), cf, of], capture_output=True, text=True)
        if p.returncode:
            print(p.stderr); return 1
        js = json.load(open(of))
    names = {v: k for k, v in item_index(D).items()}
    bad = 0
    for c, jev in zip(cases, js):
        oo = dict(c['py_opts']); oo['preview_rerolls'] = c['rr']
        pev = [list(e) for e in events(D, Run(c['seed'], D, **oo).simulate(antes))]
        if pev != jev:
            bad += 1
            for i, (x, y) in enumerate(zip(jev + [None] * 3, pev + [None] * 3)):
                if x != y:
                    print(f"MISMATCH seed={c['seed']} event {i}/{len(pev)} rr={c['rr']} opts={c['opts']}")
                    print('  JS:', x, names.get(x[4]) if x else '')
                    print('  Py:', y, names.get(y[4]) if y else '')
                    break
            if bad >= 4: break
    print(f"done: {len(cases)} cases x {antes} antes, mismatches: {bad}")
    return 1 if bad else 0

if __name__ == '__main__':
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300, int(sys.argv[2]) if len(sys.argv) > 2 else 4))
