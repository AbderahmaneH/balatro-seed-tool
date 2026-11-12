"""Glue between the Python engine and the C/OpenCL core:
   - item numbering identical to gen_data.py
   - run options -> C config array
   - Python timeline -> event stream identical to core.h's emit() calls
   - criteria parsing + matching (same rules as core.h crit_match)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Run, load_data, resolve, parse_shop_id, PACK_TAGS

E_SHOP, E_PACK, E_VOUCHER, E_TAG, E_BOSS, E_LEGEND, E_PACKTYPE, E_TOPUP = range(8)
C_LOCS = {'shop': 0, 'pack': 1, 'voucher': 2, 'tag': 3, 'boss': 4, 'legend': 5, 'packtype': 6, 'joker': 7, 'card': 8}
ED = {None: 0, 'foil': 1, 'holo': 2, 'polychrome': 3, 'negative': 4}
SEAL = {None: 0, 'red': 1, 'blue': 2, 'gold': 3, 'purple': 4}
DECK_CODE = {'b_ghost': 1, 'b_magic': 2, 'b_nebula': 3, 'b_zodiac': 4, 'b_black': 5, 'b_painted': 6}
TAGPACK_BIT = {'tag_charm': 0, 'tag_buffoon': 1, 'tag_meteor': 2, 'tag_ethereal': 3, 'tag_standard': 4}
KIND_IDX = {'s': 0, 'b': 1, 'x': 2}
CFG_SIZE = 256

_IDX = {}
def item_index(D):
    if id(D) not in _IDX:
        names = sorted(D.centers) + sorted(D.tags) + sorted(D.blinds)
        _IDX[id(D)] = {k: i for i, k in enumerate(names)}
    return _IDX[id(D)]

def card_index(D):
    return {k: i for i, k in enumerate(D.card_keys_sorted)}

def shop_index(sid):
    return (int(sid[:-1]) - 1) * 3 + KIND_IDX[sid[-1]]

def build_cfg(D, o):
    """o: dict of Run keyword options."""
    idx = item_index(D)
    cfg = [0] * CFG_SIZE
    cfg[0] = 1 if o.get('unlocked') == 'fresh' else 0
    cfg[1] = 1 if o.get('planets_played') else 0
    cfg[2] = DECK_CODE.get(o.get('deck', 'b_red'), 0)
    cfg[3] = 1 if o.get('take_souls', True) else 0
    mp = o.get('most_played')
    cfg[4] = idx[next(k for k, v in D.centers.items() if v['set'] == 'Planet' and v.get('hand_type') == mp)] if mp else -1
    cfg[5] = 1 if o.get('start_consumables', 'held') == 'held' else 0
    sk = 0
    for sid in o.get('skips', ()):
        sk |= 1 << shop_index(sid)
    cfg[6] = sk
    tp, lo, hi = 0, 0, 0
    for x in o.get('skip_packs', ()):
        if x.startswith('tagpack:'):
            tp |= 1 << TAGPACK_BIT[x[8:]]
        else:
            sid, j = x.split('.')
            bit = shop_index(sid) * 2 + int(j) - 1
            if bit < 32: lo |= 1 << bit
            else: hi |= 1 << (bit - 32)
    cfg[7] = tp
    cfg[8] = lo - (1 << 32) if lo >= 1 << 31 else lo
    cfg[9] = hi
    for sid, n in (o.get('rerolls') or {}).items():
        if shop_index(sid) < 24:
            cfg[10 + shop_index(sid)] = n
    p = 34
    for lst in ('take', 'buy_vouchers', 'own', 'locked'):
        items = list(o.get(lst, ()))
        cfg[p] = len(items); p += 1
        for k in items:
            cfg[p] = idx[k]; p += 1
    if p > CFG_SIZE:
        raise ValueError('too many items in take/buy/own/locked lists')
    return cfg

def events(D, T):
    """Python timeline -> list of (loc, game_ante, kind, rr, id, edition, seal, card) in core.h emission order."""
    idx, cidx = item_index(D), card_index(D)
    out = []
    def card_ev(loc, g, kind, rr, c):
        if c is None:
            out.append((loc, g, kind, rr, -1, 0, 0, -1)); return
        out.append((loc, g, kind, rr, idx[c['key']], ED[c.get('edition')], SEAL[(c.get('seal') or '').lower() or None],
                    cidx[c['card_key']] if 'card_key' in c else -1))
        if 'soul_gives' in c:
            L = c['soul_gives']
            out.append((E_LEGEND, g, kind, rr, idx[L['key']], ED[L.get('edition')], 0, -1))
    def round_events(g, R):
        for e in R.get('events', []):
            if e['event'] == 'tag' and e.get('cards'):
                for c in e['cards']:
                    out.append((E_TOPUP, g, 3, 0, idx[c['key']], ED[c.get('edition')], 0, -1))
            elif e['event'] == 'tag_pack' and e.get('opened'):
                for c in e['cards']:
                    card_ev(E_PACK, g, 3, 0, c)
    def shop_events(g, S):
        k = KIND_IDX[S['id'][-1]]
        for v in S['vouchers']:
            out.append((E_VOUCHER, g, k, 0, idx[v], 0, 0, -1))
        for P in S['packs']:
            out.append((E_PACKTYPE, g, k, 0, idx[P['pack']['key']], 0, 0, -1))
        for c in S['slots'][0]:
            card_ev(E_SHOP, g, k, 0, c)
        for i, pair in enumerate(S.get('preview', []), 1):
            for c in pair:
                card_ev(E_SHOP, g, k, i, c)
        for pair in S['slots'][1:]:
            for c in pair:
                card_ev(E_SHOP, g, k, 0, c)
        for P in S['packs']:
            if P['opened']:
                for c in P['cards']:
                    card_ev(E_PACK, g, k, 0, c)
    for A in T:
        g = A['ante']
        out.append((E_TAG, g, 3, 0, idx[A['tags'][0]], 0, 0, -1))
        out.append((E_TAG, g, 3, 0, idx[A['tags'][1]], 0, 0, -1))
        for R in A['rounds']:
            if R['blind'] == 'x':
                out.append((E_BOSS, g, 3, 0, idx[A['boss']], 0, 0, -1))
            if not R.get('skipped'):
                shop_events(g, R['shop'])
            round_events(g, R)
    return out

# ------------------------------------------------------------------ criteria
class Crit:
    __slots__ = ('loc', 'id', 'lo', 'hi', 'edition', 'seal', 'count', 'shopmask', 'rerolls', 'card', 'enh', 'spec', 'key', 'rarity')

    def ints(self):
        return [self.loc, self.id, self.lo, self.hi, self.edition, self.seal, self.count, self.shopmask, self.rerolls, self.card, self.enh, self.rarity]

RARITY = {'common': 1, 'uncommon': 2, 'rare': 3, 'legendary': 4}

def parse_crit(D, spec):
    """LOCATION:ITEM[:ANTES][:opt=value ...]   e.g.  legend:any:1-2:count=3   joker:Blueprint:1-3:edition=negative:rerolls=5"""
    parts = spec.split(':')
    if len(parts) < 2 or parts[0].lower() not in C_LOCS:
        raise ValueError(f"bad criterion '{spec}': LOCATION must be one of {', '.join(C_LOCS)}")
    c = Crit()
    c.spec = spec
    c.loc = C_LOCS[parts[0].lower()]
    item = parts[1].strip()
    c.lo, c.hi = 1, 1
    c.edition = c.seal = c.shopmask = c.rerolls = 0
    c.count, c.card, c.enh, c.id, c.key, c.rarity = 1, -1, -1, -1, None, 0
    rest = parts[2:]
    if rest and '=' not in rest[0]:
        a = rest.pop(0)
        if '-' in a:
            c.lo, c.hi = (int(x) for x in a.split('-'))
        else:
            c.lo = c.hi = int(a)
    idx = item_index(D)
    import re as _re
    it = _re.sub(r' jokers?$', '', _re.sub(r'^any ', '', item.lower()))
    if it in RARITY and c.loc in (C_LOCS['joker'], C_LOCS['shop'], C_LOCS['pack'], C_LOCS['legend']):
        c.rarity = RARITY[it]
        item = 'any'
    if item.lower() != 'any':
        if c.loc == C_LOCS['card']:
            cards = {v['name'].lower(): i for i, v in enumerate(D.cards[k] for k in D.card_keys_sorted)}
            if item.lower() not in cards:
                raise ValueError(f"unknown playing card '{item}' (e.g. 'Ace of Spades')")
            c.card = cards[item.lower()]
        else:
            c.key = resolve(D, item)
            c.id = idx[c.key]
            if c.loc == C_LOCS['packtype']:
                nm = D.centers[c.key]['name']
                c.key = min((k for k, v in D.centers.items() if v.get('name') == nm and v['set'] == 'Booster'), key=lambda k: idx[k])
                c.id = idx[c.key]
    for r in rest:
        k, _, v = r.partition('=')
        k, v = k.strip().lower(), v.strip()
        if k in ('edition', 'ed'):
            if v.lower() not in ED or v.lower() == 'none': raise ValueError('edition must be foil|holo|polychrome|negative')
            c.edition = ED[v.lower()]
        elif k == 'seal':
            if v.lower() not in SEAL: raise ValueError('seal must be red|blue|gold|purple')
            c.seal = SEAL[v.lower()]
        elif k in ('count', 'n'):
            c.count = int(v)
        elif k == 'shop':
            m = 0
            for x in v.lower().replace('+', ',').split(','):
                m |= 1 << {'s': 0, 'small': 0, 'b': 1, 'big': 1, 'x': 2, 'boss': 2, 'tag': 3}[x]
            c.shopmask = m
        elif k == 'rerolls':
            c.rerolls = int(v)
        elif k == 'rarity':
            if v.lower() not in RARITY: raise ValueError('rarity must be common, uncommon, rare or legendary')
            c.rarity = RARITY[v.lower()]
        elif k in ('enh', 'enhancement'):
            c.enh = idx[resolve(D, v)]
        else:
            raise ValueError(f"unknown option '{k}' in '{spec}'")
    if c.hi > 39:
        raise ValueError('antes above 39 are not supported')
    return c

def match(D, c, ev, item_kind):
    loc, g, kind, rr, iid, ed, seal, card = ev
    if g < c.lo or g > c.hi or rr > c.rerolls: return False
    if c.shopmask and not (c.shopmask >> kind) & 1: return False
    if c.edition and c.edition != ed: return False
    if c.seal and c.seal != seal: return False
    if c.rarity and (iid < 0 or item_kind['rarity'][iid] != c.rarity): return False
    L = c.loc
    idm = c.id < 0 or c.id == iid
    if L == 0: return loc == E_SHOP and idm
    if L == 1: return loc == E_PACK and idm
    if L == 2: return loc == E_VOUCHER and idm
    if L == 3: return loc == E_TAG and idm
    if L == 4: return loc == E_BOSS and idm
    if L == 5: return loc == E_LEGEND and idm
    if L == 6: return loc == E_PACKTYPE and (c.id < 0 or c.id == item_kind['group'][iid])
    if L == 7: return loc in (E_SHOP, E_PACK, E_LEGEND, E_TOPUP) and iid >= 0 and item_kind['kind'][iid] == 1 and idm
    if L == 8: return loc in (E_SHOP, E_PACK) and card >= 0 and (c.card < 0 or c.card == card) and (c.enh < 0 or c.enh == iid)
    return False

_KINDS = {}
def item_kinds(D):
    if id(D) not in _KINDS:
        idx = item_index(D)
        names = sorted(idx, key=idx.get)
        kind, group, first, rarity = [], [], {}, []
        kc = {'Joker': 1, 'Tarot': 2, 'Planet': 3, 'Spectral': 4, 'Enhanced': 5, 'Voucher': 6, 'Booster': 7}
        for k in names:
            c = D.centers.get(k)
            kind.append(kc.get(c['set'], 0) if c else 0)
            rarity.append((c.get('rarity') or 0) if c and c['set'] == 'Joker' else 0)
            if c and c['set'] == 'Booster':
                first.setdefault(c['name'], idx[k]); group.append(first[c['name']])
            else:
                group.append(idx[k])
        _KINDS[id(D)] = dict(kind=kind, group=group, rarity=rarity)
    return _KINDS[id(D)]

def py_check(seed, D, opts, crits, detail=False):
    antes = max(c.hi for c in crits)
    o = dict(opts); o['preview_rerolls'] = max(c.rerolls for c in crits)
    run = Run(seed, D, **o)
    T = run.simulate(antes)
    ik = item_kinds(D)
    cnt = [0] * len(crits)
    where = [[] for _ in crits]
    for ev in events(D, T):
        for i, c in enumerate(crits):
            if match(D, c, ev, ik):
                cnt[i] += 1
                where[i].append(ev)
    ok = all(cnt[i] >= c.count for i, c in enumerate(crits))
    return (ok, where, T) if detail else ok
