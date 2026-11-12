#!/usr/bin/env python3
"""
Balatro seed analyzer - every shop of every ante, pack contents, Souls/legendaries, vouchers, tags, bosses.

  python analyze.py ALEEB                       # antes 1-3, text
  python analyze.py ALEEB --antes 8 --format md --out ALEEB.md
  python analyze.py ALEEB --skip 1s --reroll 1b=2 --buy-voucher Overstock --preview-rerolls 3

Run `python analyze.py -h` for every option (also documented in GUIDE.md / GUIDE.pdf).
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import (Run, load_data, valid_seed, first_legendary, resolve, resolve_deck, resolve_stake,
                    item_name, parse_shop_id, STAKES, SHOP_LABEL)

def split_list(vals):
    out = []
    for v in vals or []:
        out += [x.strip() for x in v.split(',') if x.strip()]
    return out

def build_opts(a, D):
    """argparse namespace -> Run keyword options (shared by analyze.py and find_seeds.py)."""
    rer = {}
    for x in split_list(a.reroll):
        sid, _, n = x.partition('=')
        rer[parse_shop_id(sid)] = int(n or 1)
    skip_packs = set()
    for x in split_list(a.skip_pack):
        if x.lower().startswith('tag:'):
            skip_packs.add('tagpack:' + resolve(D, x[4:], ('tags',)))
        else:
            sid, _, j = x.partition('.')
            skip_packs.add(f"{parse_shop_id(sid)}.{int(j or 1)}")
    skips = set()
    for x in split_list(a.skip):
        sid = parse_shop_id(x)
        if sid.endswith('x'):
            raise SystemExit("The Boss Blind cannot be skipped")
        skips.add(sid)
    mp = None
    if a.most_played:
        hands = {(v.get('hand_type') or '').lower(): v['hand_type'] for v in D.centers.values() if v['set'] == 'Planet'}
        if a.most_played.lower() not in hands:
            raise ValueError(f"unknown hand '{a.most_played}' (one of: {', '.join(sorted(set(hands.values())))})")
        mp = hands[a.most_played.lower()]
    return dict(unlocked=a.unlocked, deck=resolve_deck(D, a.deck), stake=resolve_stake(a.stake),
                planets_played=a.planets_played, locked=[resolve(D, x) for x in split_list(a.locked)],
                own=[resolve(D, x) for x in split_list(a.own)],
                buy_vouchers=[resolve(D, x) for x in split_list(a.buy_voucher)],
                take=[resolve(D, x) for x in split_list(a.take)], take_souls=not a.no_souls,
                most_played=mp, skips=skips, rerolls=rer, skip_packs=skip_packs,
                start_consumables=a.start_consumables)

def add_common_args(ap):
    g = ap.add_argument_group('run setup')
    g.add_argument('--deck', default='Red', help='deck name or key (Red, Ghost, Magic, Nebula, Zodiac, ...)')
    g.add_argument('--stake', default='1', help='1-8 or White..Gold (stickers from Black stake up)')
    g.add_argument('--unlocked', choices=['all', 'fresh'], default='all', help='all = every joker/voucher unlocked (default); fresh = new profile')
    g.add_argument('--locked', action='append', help='items still locked on your profile (comma list) - removed from pools')
    g.add_argument('--planets-played', action='store_true', help='Planet X / Ceres / Eris can appear (secret hands played)')
    g = ap.add_argument_group('what you do during the run')
    g.add_argument('--skip', action='append', help='blinds you skip, e.g. 1s,2b (s=small b=big). Skipped blind = no shop, you get its tag')
    g.add_argument('--reroll', action='append', help='rerolls per shop, e.g. 1s=2,2b=1  (shops: 1s 1b 1x = after small/big/boss of ante 1)')
    g.add_argument('--skip-pack', action='append', help="packs you don't open, e.g. 1s.1 (shop 1s, pack 1) or tag:Charm")
    g.add_argument('--buy-voucher', action='append', help='vouchers you buy as soon as they are offered (Overstock, Tarot Merchant, Magic Trick, ...)')
    g.add_argument('--take', action='append', help='jokers/cards you buy or pick whenever they show up (they become owned)')
    g.add_argument('--own', action='append', help='jokers you already have (e.g. Showman allows duplicates)')
    g.add_argument('--no-souls', action='store_true', help="don't take/use The Soul (default: every Soul is taken and used)")
    g.add_argument('--most-played', help='your most played hand (only matters with Telescope), e.g. "Flush"')
    g.add_argument('--start-consumables', choices=['held', 'used'], default='held', help='Magic/Ghost deck starting cards')

# ------------------------------------------------------------------------------- rendering
def card_txt(D, c, md=False):
    if c is None:
        return '(empty)'
    b = (lambda s: f"**{s}**") if md else (lambda s: s)
    if 'card' in c:
        s = c['card'] + ('' if c['key'] == 'c_base' else f" ({c['name']})")
    else:
        s = c['name']
    extra = []
    if c.get('edition'): extra.append(c['edition'].capitalize() + (' via tag' if c.get('edition_from_tag') else ''))
    if c.get('seal'): extra.append(c['seal'] + ' Seal')
    if c.get('sticker'): extra.append(c['sticker'].capitalize())
    if c.get('rental'): extra.append('Rental')
    if c.get('from_tag'): extra.append('from ' + c['from_tag'])
    if extra: s += ' [' + ', '.join(extra) + ']'
    if c['key'] == 'c_soul':
        s = b('THE SOUL')
        if 'soul_gives' in c:
            L = c['soul_gives']
            s += ' -> ' + b(L['name'] + (f" ({L['edition'].capitalize()})" if L.get('edition') else ''))
    elif c['key'] == 'c_black_hole':
        s = b('BLACK HOLE')
    if c.get('taken') and c['key'] != 'c_soul':
        s += ' (taken)'
    return s

def render(D, a, run, T, fmt):
    md = fmt == 'md'
    L = []
    w = L.append
    deckname = D.centers[run.deck]['name']
    hdr = f"Seed {run.seed} | {deckname} | {STAKES[run.stake - 1]} Stake | {'all unlocked' if run.unlocked_mode == 'all' else 'fresh profile'}"
    w(('# ' if md else '') + hdr)
    w(f"Game's own first-legendary prediction (get_first_legendary): {first_legendary(run.seed, D)}")
    legs = []
    for A in T:
        for R in A['rounds']:
            srcs = []
            if R.get('shop'):
                for P in R['shop']['packs']:
                    srcs += [(f"ante {A['ante']} shop {SHOP_LABEL[R['blind']]}, {P['pack']['name']}", c) for c in P.get('cards', [])]
            for e in R.get('events', []):
                if e.get('cards'):
                    srcs += [(f"ante {A['ante']} {D.tags[e['tag']]['name']}", c) for c in e['cards']]
            for where, c in srcs:
                if 'soul_gives' in c:
                    legs.append(f"{c['soul_gives']['name']}{' (' + c['soul_gives']['edition'] + ')' if c['soul_gives'].get('edition') else ''} - {where}")
    if legs:
        w('')
        w(('## ' if md else '') + f"Legendaries from The Soul ({len(legs)})")
        for x in legs:
            w(('- ' if md else '  * ') + x)
    for A in T:
        g = A['ante']
        w('')
        w((f"## Ante {g}" if md else f"=================== ANTE {g} ===================") )
        w(f"Boss: {D.blinds[A['boss']]['name']}   |   Skip tags: Small -> {D.tags[A['tags'][0]]['name']}, Big -> {D.tags[A['tags'][1]]['name']}")
        for R in A['rounds']:
            blindname = {'s': 'Small Blind', 'b': 'Big Blind', 'x': f"Boss Blind ({D.blinds[A['boss']]['name']})"}[R['blind']]
            if R.get('skipped'):
                w('')
                w((f"### {blindname}: SKIPPED" if md else f"-- {blindname}: SKIPPED") + f" -> {D.tags[R['tag']]['name']}")
            else:
                S = R['shop']
                w('')
                note = f"  (new ante: rolled with ante {S['rng_ante']} RNG)" if R['blind'] == 'x' else ''
                w((f"### Shop {S['label']}" if md else f"-- Shop {S['label']}") + f"   [{S['id']}]" + note)
                pre = '- ' if md else '   '
                w(pre + "Voucher: " + (', '.join(item_name(D, v) + (' (bought)' if v in S['bought_vouchers'] else '') for v in S['vouchers']) or '(none)'))
                for i, pair in enumerate(S['slots']):
                    lab = 'Shop cards' if i == 0 else f'After reroll {i}'
                    w(pre + f"{lab}: " + ' | '.join(card_txt(D, c, md) for c in pair))
                for i, pair in enumerate(S.get('preview', []), 1):
                    w(pre + f"(if you reroll {i}x): " + ' | '.join(card_txt(D, c, md) for c in pair))
                for j, P in enumerate(S['packs'], 1):
                    p = P['pack']
                    head = f"Pack {j}: {p['name']} (choose {p.get('choose') or 1} of {p['extra']})"
                    if not P['opened']:
                        w(pre + head + ': not opened')
                    else:
                        w(pre + head + ': ' + ', '.join(card_txt(D, c, md) for c in P['cards']))
            for e in R.get('events', []):
                if e['event'] == 'tag_pack':
                    txt = f"{D.tags[e['tag']]['name']} opens {e['pack']['name']}: " + (', '.join(card_txt(D, c, md) for c in e['cards']) if e['opened'] else 'not opened')
                elif e['event'] == 'double':
                    txt = f"Double Tag copies {D.tags[e['tag']]['name']}"
                elif e.get('boss'):
                    txt = f"Boss Tag rerolls the boss -> {D.blinds[e['boss']]['name']}"
                elif e.get('cards'):
                    txt = f"{D.tags[e['tag']]['name']}: " + ', '.join(card_txt(D, c, md) for c in e['cards'])
                else:
                    txt = f"{D.tags[e['tag']]['name']} used"
                w(('- ' if md else '   ') + 'Tag: ' + txt)
    w('')
    w(('> ' if md else '') + "Model: no rerolls/purchases unless given as options; slot cards bought before packs are opened; packs opened left to right; "
      "every Soul taken and used at once. Pack contents depend on the order you open packs.")
    for x in run.warnings:
        w(('> ' if md else '') + 'Warning: ' + x)
    return '\n'.join(L)

def to_json(D, run, T):
    def clean(o):
        if isinstance(o, dict):
            if 'kind' in o and 'weight' in o:      # booster center
                return {'key': o['key'], 'name': o['name']}
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(x) for x in o]
        return o
    return json.dumps(dict(seed=run.seed, deck=run.deck, stake=run.stake, antes=clean(T), warnings=run.warnings), indent=1)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('seed')
    ap.add_argument('--antes', type=int, default=3)
    ap.add_argument('--preview-rerolls', type=int, default=0, help='also show what the next N rerolls of every shop would give (does not change the run)')
    ap.add_argument('--format', choices=['text', 'md', 'json'], default='text')
    ap.add_argument('--out', help='write to this file instead of the screen')
    add_common_args(ap)
    a = ap.parse_args()
    a.seed = a.seed.upper()
    if not valid_seed(a.seed):
        sys.exit('Seed must be 1-8 characters from 1-9, A-N, P-Z (no 0 or O).')
    D = load_data()
    try:
        run = Run(a.seed, D, preview_rerolls=a.preview_rerolls, **build_opts(a, D))
    except ValueError as e:
        sys.exit(str(e))
    T = run.simulate(a.antes)
    txt = to_json(D, run, T) if a.format == 'json' else render(D, a, run, T, a.format)
    if a.out:
        open(a.out, 'w', encoding='utf-8').write(txt + '\n')
        print('wrote', a.out)
    else:
        print(txt)

if __name__ == '__main__':
    main()
