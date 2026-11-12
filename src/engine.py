"""
Balatro seed engine - a re-implementation of the game's own seed logic, built from the
Lua sources (game.lua / misc_functions.lua / common_events.lua / UI_definitions.lua).

Pure Python, no dependencies.  Exactness hinges on three things:
  1. pseudohash / pseudoseed  - ported 1:1 from misc_functions.lua
  2. LuaJIT's math.randomseed / math.random (Tausworthe-223 PRNG) - ported from LuaJIT lj_math.c
  3. the pool construction + draw order from common_events.lua

Anything NOT contained in the uploaded Lua files (Card:open pack contents, deck shuffle,
tag/voucher rollover per ante) is marked ASSUMED below.
"""
import math, re, os

MASK64 = (1 << 64) - 1
PI = math.pi
SEED_CHARS = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"

# ----------------------------------------------------------------------------------------
# LuaJIT PRNG (lib_math.c): 4 x 64-bit Tausworthe, seeded from a double
# ----------------------------------------------------------------------------------------
import struct

def _d2u(d):
    return struct.unpack('<Q', struct.pack('<d', d))[0]

def _u2d(u):
    return struct.unpack('<d', struct.pack('<Q', u))[0]

_TW = ((63, 31, 18), (58, 19, 28), (55, 24, 7), (47, 21, 8))

class LuaRandom:
    __slots__ = ('u',)

    def __init__(self):
        self.u = [0, 0, 0, 0]

    def _step(self):
        r = 0
        u = self.u
        for i, (k, q, s) in enumerate(_TW):
            z = u[i]
            z = ((((z << q) & MASK64) ^ z) >> (k - s)) ^ (((z & ((MASK64 << (64 - k)) & MASK64)) << s) & MASK64)
            r ^= z
            u[i] = z
        return r

    def seed(self, d):
        r = 0x11090601
        d = float(d)
        for i in range(4):
            m = 1 << (r & 255)
            r >>= 8
            d = d * PI + 2.7182818284590452354
            uu = _d2u(d)
            if uu < m:
                uu += m
            self.u[i] = uu
        for _ in range(10):
            self._step()

    def random(self):
        r = self._step()
        return _u2d((r & 0x000fffffffffffff) | 0x3ff0000000000000) - 1.0

    def randint(self, lo, hi=None):
        if hi is None:
            lo, hi = 1, lo
        return int(math.floor(self.random() * (hi - lo + 1))) + lo


# ----------------------------------------------------------------------------------------
# pseudohash / pseudoseed (misc_functions.lua)
# ----------------------------------------------------------------------------------------
def pseudohash(s):
    num = 1.0
    b = s.encode('latin-1', 'replace') if isinstance(s, str) else s
    for i in range(len(b), 0, -1):
        num = ((1.1239285023 / num) * b[i - 1] * PI + PI * i) % 1.0
    return num

def _step_state(x):
    return abs(float("%.13f" % ((2.134453429141 + x * 1.72431234) % 1.0)))


# ----------------------------------------------------------------------------------------
# Game data parsed straight out of game.lua
# ----------------------------------------------------------------------------------------
def _find_game_lua(path=None):
    cands = [path] if path else []
    here = os.path.dirname(os.path.abspath(__file__))
    cands += [os.path.join(here, '..', 'data', 'game.lua'), os.path.join(here, 'game.lua'), os.path.join(here, 'data', 'game.lua'),
              'game.lua']
    for c in cands:
        if c and os.path.exists(c):
            return c
    # no game.lua: fall back to the tables extracted from it (data/game_data.json, see tools/export_game_data.py)
    for c in (os.path.join(here, '..', 'data', 'game_data.json'), os.path.join(here, 'data', 'game_data.json')):
        if os.path.exists(c):
            return c
    raise FileNotFoundError("game data not found - put game.lua (from your Balatro install) or game_data.json in data/")

_ENTRY = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{(.*)\}\s*,?\s*(?:--.*)?$')

def _field(body, name, cast=str):
    m = re.search(r'(?<![A-Za-z_])' + name + r'\s*=\s*("([^"]*)"|\'([^\']*)\'|[-0-9.]+|true|false|nil)', body)
    if not m:
        return None
    v = m.group(1)
    if v[0] in '"\'':
        return v[1:-1]
    if v == 'true': return True
    if v == 'false': return False
    if v == 'nil': return None
    f = float(v)
    return int(f) if f == int(f) else f

def _section(lines, start_pat, end_pat):
    out, on = [], False
    for ln in lines:
        if not on and re.search(start_pat, ln):
            on = True
            continue
        if on:
            if re.match(end_pat, ln):
                break
            out.append(ln)
    return out

class GameData:
    def __init__(self, path=None):
        src = _find_game_lua(path)
        if src.endswith('.json'):
            import json
            with open(src, encoding='utf-8') as f:
                d = json.load(f)
            self.centers, self.tags, self.blinds, self.cards = d['centers'], d['tags'], d['blinds'], d['cards']
        else:
            self._parse_lua(src)
        self._build_pools()

    def export(self):
        """The four tables the engines need, as plain JSON-able dicts."""
        return {'centers': self.centers, 'tags': self.tags, 'blinds': self.blinds, 'cards': self.cards}

    def _parse_lua(self, src):
        with open(src, encoding='utf-8', errors='replace') as f:
            lines = f.read().split('\n')
        self.centers, self.tags, self.blinds, self.cards = {}, {}, {}, {}

        for ln in _section(lines, r'self\.P_CENTERS\s*=\s*\{', r'^\s*\}\s*$'):
            m = _ENTRY.match(ln)
            if not m: continue
            k, body = m.groups()
            c = dict(key=k, order=_field(body, 'order') or 0, set=_field(body, 'set'),
                     name=_field(body, 'name'), rarity=_field(body, 'rarity'),
                     unlocked=_field(body, 'unlocked'), cost=_field(body, 'cost'),
                     kind=_field(body, 'kind'), weight=_field(body, 'weight'),
                     no_pool_flag=_field(body, 'no_pool_flag'),
                     yes_pool_flag=_field(body, 'yes_pool_flag'),
                     enhancement_gate=_field(body, 'enhancement_gate'),
                     wip=_field(body, 'wip'), demo=_field(body, 'demo'),
                     omit=_field(body, 'omit'), skip_pool=_field(body, 'skip_pool'),
                     softlock=('softlock = true' in body or 'softlock=true' in body),
                     extra=_field(body, 'extra'), choose=_field(body, 'choose'),
                     hand_type=_field(body, 'hand_type'))
            rq = re.search(r'requires\s*=\s*\{([^}]*)\}', body)
            c['requires'] = re.findall(r"'([^']+)'", rq.group(1)) if rq else None
            self.centers[k] = c

        for ln in _section(lines, r'self\.P_TAGS\s*=\s*\{', r'^\s*\}\s*,?\s*$'):
            m = _ENTRY.match(ln)
            if not m: continue
            k, body = m.groups()
            rq = re.search(r"requires\s*=\s*'([^']+)'", body)
            self.tags[k] = dict(key=k, name=_field(body, 'name'), order=_field(body, 'order'),
                                min_ante=_field(body, 'min_ante'), requires=rq.group(1) if rq else None)

        for ln in _section(lines, r'self\.P_BLINDS\s*=\s*\{', r'^\s*\}\s*,?\s*$'):
            m = _ENTRY.match(ln)
            if not m: continue
            k, body = m.groups()
            bm = re.search(r'boss\s*=\s*\{([^}]*)\}', body)
            boss = None
            if bm:
                b = bm.group(1)
                boss = dict(min=_field(b, 'min'), max=_field(b, 'max'), showdown=bool(_field(b, 'showdown')))
            self.blinds[k] = dict(key=k, name=_field(body, 'name'), order=_field(body, 'order'), boss=boss)

        for ln in _section(lines, r'self\.P_CARDS\s*=\s*\{', r'^\s*\}\s*,?\s*$'):
            m = _ENTRY.match(ln)
            if not m: continue
            k, body = m.groups()
            self.cards[k] = dict(key=k, name=_field(body, 'name'))

    def _build_pools(self):
        # pools exactly as Game:init_item_prototypes builds them (sorted by .order)
        live = [c for c in self.centers.values() if not c['wip']]
        by_order = lambda c: c['order']
        self.pool = {}
        for s in ('Booster', 'Tarot', 'Planet', 'Spectral', 'Voucher', 'Enhanced', 'Back'):
            self.pool[s] = sorted([c for c in live if c['set'] == s and not c['skip_pool'] and not c['omit']], key=by_order)
        self.pool['Joker'] = sorted([c for c in self.centers.values() if c['set'] == 'Joker'], key=by_order)
        self.rarity_pool = {r: sorted([c for c in live if c['set'] == 'Joker' and not c['demo'] and c['rarity'] == r], key=by_order)
                            for r in (1, 2, 3, 4)}
        self.tag_pool = sorted(self.tags.values(), key=lambda t: t['order'])
        self.card_keys_sorted = sorted(self.cards.keys())      # pseudorandom_element sorts string keys
        # Lua `a.k < b.k` on strings == byte order == Python str order for ASCII
        self.blind_keys_sorted = sorted(self.blinds.keys())

_DATA = {}
def load_data(path=None):
    key = path or ''
    if key not in _DATA:
        _DATA[key] = GameData(path)
    return _DATA[key]




# ========================================================================================
# Run simulation  (v2: real shop timeline + the game's "card already exists" exclusions)
# ========================================================================================
def valid_seed(s):
    return 0 < len(s) <= 8 and all(ch in SEED_CHARS for ch in s)

EDITIONS = ('foil', 'holo', 'polychrome', 'negative')
PACK_TAGS = {'tag_charm': 'p_arcana_mega_1', 'tag_buffoon': 'p_buffoon_mega_1', 'tag_meteor': 'p_celestial_mega_1',
             'tag_ethereal': 'p_spectral_normal_1', 'tag_standard': 'p_standard_mega_1'}
TAG_TYPE = {'tag_uncommon': 'store_joker_create', 'tag_rare': 'store_joker_create',
            'tag_negative': 'store_joker_modify', 'tag_foil': 'store_joker_modify', 'tag_holo': 'store_joker_modify',
            'tag_polychrome': 'store_joker_modify', 'tag_investment': 'eval', 'tag_voucher': 'voucher_add',
            'tag_boss': 'new_blind_choice', 'tag_standard': 'new_blind_choice', 'tag_charm': 'new_blind_choice',
            'tag_meteor': 'new_blind_choice', 'tag_buffoon': 'new_blind_choice', 'tag_ethereal': 'new_blind_choice',
            'tag_handy': 'immediate', 'tag_garbage': 'immediate', 'tag_top_up': 'immediate', 'tag_skip': 'immediate',
            'tag_orbital': 'immediate', 'tag_economy': 'immediate', 'tag_coupon': 'shop_final_pass',
            'tag_double': 'tag_add', 'tag_juggle': 'round_start_bonus', 'tag_d_six': 'shop_start'}
SHOP_KINDS = ('s', 'b', 'x')      # shop after Small blind, Big blind, Boss blind
SHOP_LABEL = {'s': 'after Small Blind', 'b': 'after Big Blind', 'x': 'after Boss Blind'}

def shop_id(game_ante, kind):
    return f"{game_ante}{kind}"

def parse_shop_id(s):
    """'1s' / '1small' / '2b' / '2big' / '3x' / '3boss' -> '1s' etc."""
    s = s.strip().lower()
    num = ''.join(ch for ch in s if ch.isdigit())
    rest = s[len(num):]
    k = {'s': 's', 'small': 's', 'b': 'b', 'big': 'b', 'x': 'x', 'boss': 'x'}.get(rest)
    if not num or not k:
        raise ValueError(f"bad shop/blind id '{s}' (use e.g. 1s, 1b, 1x / 1small, 1big, 1boss)")
    return f"{int(num)}{k}"


class Run:
    """One run of the game. Call simulate(antes) once; it returns the full timeline."""

    def __init__(self, seed, data=None, *, unlocked='all', deck='b_red', stake=1, planets_played=False,
                 locked=(), own=(), buy_vouchers=(), take=(), take_souls=True, most_played=None,
                 skips=(), rerolls=None, skip_packs=(), preview_rerolls=0, start_consumables='held'):
        self.seed = seed.upper()
        self.D = data or load_data()
        self.unlocked_mode = unlocked
        self.locked = set(locked)
        self.stake = stake
        self.planets_played = planets_played
        self.take = set(take)
        self.take_souls = take_souls
        self.most_played = most_played
        self.buy_vouchers = set(buy_vouchers)
        self.skips = set(skips)
        self.rerolls = dict(rerolls or {})
        self.skip_packs = set(skip_packs)
        self.preview_rerolls = preview_rerolls
        self.warnings = []

        self.rng = LuaRandom()
        self.streams = {}
        self.hashed_seed = pseudohash(self.seed)
        self.ante = 1                      # G.GAME.round_resets.ante  (the number used in RNG keys)
        self.used = set()                  # G.GAME.used_jokers : centers of every card that currently exists
        self.jokers = []                   # owned jokers (dicts)
        self.consumables = []
        self.used_vouchers = set()
        self.tags = []                     # held tags (keys), in acquisition order
        self.bosses_used = {k: 0 for k, v in self.D.blinds.items() if v['boss']}
        self.joker_rate, self.tarot_rate, self.planet_rate = 20, 4, 4
        self.playing_card_rate, self.spectral_rate = 0, 0
        self.edition_rate = 1
        self.joker_max = 2
        self.joker_slots = 5 + {'b_black': 1, 'b_painted': -1}.get(deck, 0)
        self.first_shop_buffoon = False
        self.shop_voucher_keys = set()
        self.shop_cards = None             # list of current shop slot cards while in a shop
        self.deck = deck
        self._apply_deck(deck, start_consumables)
        for k in own:
            self._gain_joker(dict(type='Joker', key=k, name=self.D.centers[k]['name']))

    # ---------------- deck / vouchers -------------------------------------------------------
    def _apply_deck(self, deck, start_consumables):
        cfg = {'b_ghost': dict(spectral_rate=2, consumables=['c_hex']),
               'b_magic': dict(vouchers=['v_crystal_ball'], consumables=['c_fool', 'c_fool']),
               'b_nebula': dict(vouchers=['v_telescope']),
               'b_zodiac': dict(vouchers=['v_tarot_merchant', 'v_planet_merchant', 'v_overstock_norm'])}.get(deck, {})
        if 'spectral_rate' in cfg:
            self.spectral_rate = cfg['spectral_rate']
        for v in cfg.get('vouchers', []):
            self.redeem_voucher(v, in_shop=False)
        if start_consumables == 'held':
            for c in cfg.get('consumables', []):
                self.consumables.append(c)
                self.used.add(c)

    def redeem_voucher(self, v, in_shop=True):
        self.used_vouchers.add(v)
        if v == 'v_tarot_merchant': self.tarot_rate = 9.6
        elif v == 'v_tarot_tycoon': self.tarot_rate = 32
        elif v == 'v_planet_merchant': self.planet_rate = 9.6
        elif v == 'v_planet_tycoon': self.planet_rate = 32
        elif v in ('v_magic_trick', 'v_illusion'): self.playing_card_rate = 4
        elif v == 'v_hone': self.edition_rate = 2
        elif v == 'v_glow_up': self.edition_rate = 4
        elif v in ('v_overstock_norm', 'v_overstock_plus'):
            self.joker_max += 1
            if in_shop and self.shop_cards is not None:        # change_shop_size(1): adds a card right away
                while len(self.shop_cards) < self.joker_max:
                    self.shop_cards.append(self.shop_slot())

    # ---------------- RNG primitives ----------------------------------------------------------
    def pseudoseed(self, key):
        st = self.streams.get(key)
        if st is None:
            st = pseudohash(key + self.seed)
        st = _step_state(st)
        self.streams[key] = st
        return (st + self.hashed_seed) / 2

    def pseudorandom(self, key_or_seed):
        s = self.pseudoseed(key_or_seed) if isinstance(key_or_seed, str) else key_or_seed
        self.rng.seed(s)
        return self.rng.random()

    def pick_index(self, n, seedval):
        self.rng.seed(seedval)
        return self.rng.randint(n)

    # ---------------- existence tracking (G.GAME.used_jokers) ---------------------------------
    def showman(self):
        return any(j['key'] == 'j_ring_master' for j in self.jokers)

    def _created(self, key):              # Card:set_ability
        self.used.add(key)

    def _removed(self, key):              # Card:remove -> cleared unless an owned joker of that name exists
        if not any(j['key'] == key for j in self.jokers):
            self.used.discard(key)

    def _free_joker_slots(self):
        neg = sum(1 for j in self.jokers if j.get('edition') == 'negative')
        return self.joker_slots + neg - len(self.jokers)

    def _gain_joker(self, card):
        self.jokers.append(card)
        self.used.add(card['key'])

    # ---------------- pools (get_current_pool) -----------------------------------------------
    def _unlock_ok(self, v):
        if v['key'] in self.locked:
            return False
        return self.unlocked_mode == 'all' or v.get('unlocked') is not False or v.get('rarity') == 4

    def get_current_pool(self, typ, rarity=None, legendary=False, append=''):
        D, ante = self.D, self.ante
        if typ == 'Joker':
            r = rarity if rarity is not None else self.pseudorandom('rarity' + str(ante) + (append or ''))
            rr = 4 if legendary else (3 if r > 0.95 else (2 if r > 0.7 else 1))
            starting = D.rarity_pool[rr]
            pool_key = 'Joker' + str(rr) + ('' if legendary else (append or ''))
        elif typ == 'Tag':
            starting, pool_key = D.tag_pool, 'Tag' + (append or '')
        else:
            starting, pool_key = D.pool[typ], typ + (append or '')
        showman = self.showman()
        pool, size = [], 0
        for v in starting:
            add = None
            if typ == 'Tag':
                if ((not v['requires']) or self.unlocked_mode == 'all') and (not v['min_ante'] or v['min_ante'] <= ante):
                    add = True
            elif typ == 'Enhanced':
                add = True
            elif not (v['key'] in self.used and not showman) and self._unlock_ok(v):
                if v['set'] == 'Voucher':
                    if v['key'] not in self.used_vouchers:
                        include = all(rq in self.used_vouchers for rq in (v['requires'] or []))
                        if v['key'] in self.shop_voucher_keys:
                            include = False
                        if include:
                            add = True
                elif v['set'] == 'Planet':
                    if (not v['softlock']) or self.planets_played:
                        add = True
                elif v['enhancement_gate']:
                    add = None
                else:
                    add = True
                if v['name'] in ('Black Hole', 'The Soul'):
                    add = False
            if v.get('yes_pool_flag'):
                add = None
            if add:
                pool.append(v['key']); size += 1
            else:
                pool.append('UNAVAILABLE')
        if size == 0:
            pool = [dict(Tarot='c_strength', Planet='c_pluto', Spectral='c_incantation', Joker='j_joker',
                         Voucher='v_blank', Tag='tag_handy').get(typ, 'j_joker')]
        return pool, pool_key + ('' if legendary else str(ante))

    def draw_from_pool(self, pool, pool_key):
        c = pool[self.pick_index(len(pool), self.pseudoseed(pool_key)) - 1]
        it = 1
        while c == 'UNAVAILABLE':
            it += 1
            c = pool[self.pick_index(len(pool), self.pseudoseed(pool_key + '_resample' + str(it))) - 1]
        return c

    def poll_edition(self, key, mod=1, no_neg=False, guaranteed=False):
        p = self.pseudorandom(key)
        if guaranteed:
            if p > 1 - 0.003 * 25 and not no_neg: return 'negative'
            if p > 1 - 0.006 * 25: return 'polychrome'
            if p > 1 - 0.02 * 25: return 'holo'
            if p > 1 - 0.04 * 25: return 'foil'
        else:
            if p > 1 - 0.003 * mod and not no_neg: return 'negative'
            if p > 1 - 0.006 * self.edition_rate * mod: return 'polychrome'
            if p > 1 - 0.02 * self.edition_rate * mod: return 'holo'
            if p > 1 - 0.04 * self.edition_rate * mod: return 'foil'
        return None

    # ---------------- create_card (common_events.lua) -----------------------------------------
    def create_card(self, typ, area, legendary=False, rarity=None, soulable=False, forced_key=None, append=''):
        ante, D = self.ante, self.D
        showman = self.showman()
        if not forced_key and soulable:
            if typ in ('Tarot', 'Spectral', 'Tarot_Planet') and not ('c_soul' in self.used and not showman):
                if self.pseudorandom('soul_' + typ + str(ante)) > 0.997:
                    forced_key = 'c_soul'
            if typ in ('Planet', 'Spectral') and not ('c_black_hole' in self.used and not showman):
                if self.pseudorandom('soul_' + typ + str(ante)) > 0.997:
                    forced_key = 'c_black_hole'
        if typ == 'Base':
            forced_key = 'c_base'
        if forced_key:
            key = forced_key
            if D.centers[key]['set'] != 'Default':
                typ = D.centers[key]['set']
        else:
            pool, pool_key = self.get_current_pool(typ, rarity, legendary, append)
            key = self.draw_from_pool(pool, pool_key)
        card = dict(type=typ, key=key, name=D.centers[key]['name'])
        if typ in ('Base', 'Enhanced'):
            keys = D.card_keys_sorted
            ck = keys[self.pick_index(len(keys), self.pseudoseed('front' + (append or '') + str(ante))) - 1]
            card['card'] = D.cards[ck]['name']; card['card_key'] = ck
        self._created(key)
        if typ == 'Joker':
            if area in ('shop', 'pack'):
                poll = self.pseudorandom(('packetper' if area == 'pack' else 'etperpoll') + str(ante))
                if self.stake >= 4 and poll > 0.7: card['sticker'] = 'eternal'
                elif self.stake >= 7 and 0.4 < poll <= 0.7: card['sticker'] = 'perishable'
                if self.stake >= 8 and self.pseudorandom(('packssjr' if area == 'pack' else 'ssjr') + str(ante)) > 0.7:
                    card['rental'] = True
            ed = self.poll_edition('edi' + (append or '') + str(ante))
            if ed: card['edition'] = ed
        return card

    # ---------------- shop slot (create_card_for_shop, UI_definitions.lua) --------------------
    def shop_slot(self):
        # store_joker_create tags (Uncommon / Rare)  -- tag.lua not provided: key_append 'uta'/'rta' ASSUMED
        for i, t in enumerate(self.tags):
            if TAG_TYPE.get(t) == 'store_joker_create':
                if t == 'tag_uncommon':
                    card = self.create_card('Joker', 'shop', rarity=0.9, append='uta')
                else:
                    card = self.create_card('Joker', 'shop', rarity=1, append='rta')
                card['from_tag'] = self.D.tags[t]['name']
                del self.tags[i]
                self._modify_tags(card)
                return card
        total = self.joker_rate + self.tarot_rate + self.planet_rate + self.playing_card_rate + self.spectral_rate
        polled = self.pseudorandom(self.pseudoseed('cdt' + str(self.ante))) * total
        illusion = 'v_illusion' in self.used_vouchers
        pc_type = 'Base'
        if illusion and self.pseudorandom(self.pseudoseed('illusion')) > 0.6:
            pc_type = 'Enhanced'
        check = 0
        for typ, val in (('Joker', self.joker_rate), ('Tarot', self.tarot_rate), ('Planet', self.planet_rate),
                         (pc_type, self.playing_card_rate), ('Spectral', self.spectral_rate)):
            if polled > check and polled <= check + val:
                card = self.create_card(typ, 'shop', append='sho')
                self._modify_tags(card)
                if typ in ('Base', 'Enhanced') and illusion and self.pseudorandom(self.pseudoseed('illusion')) > 0.8:
                    ep = self.pseudorandom(self.pseudoseed('illusion'))
                    card['edition'] = 'polychrome' if ep > 1 - 0.15 else ('holo' if ep > 0.5 else 'foil')
                return card
            check += val
        return None

    def _modify_tags(self, card):
        if card['type'] != 'Joker' or card.get('edition'):
            return
        for i, t in enumerate(self.tags):
            if TAG_TYPE.get(t) == 'store_joker_modify':
                card['edition'] = t[4:]          # tag_foil -> foil ...
                card['edition_from_tag'] = True
                del self.tags[i]
                return

    # ---------------- vouchers / tags / boss / packs ------------------------------------------
    def next_voucher(self, from_tag=False):
        pool, key = self.get_current_pool('Voucher')
        if from_tag:
            key = 'Voucher_fromtag'
        return self.draw_from_pool(pool, key)

    def next_tag(self):
        pool, key = self.get_current_pool('Tag')
        return self.draw_from_pool(pool, key)

    def get_pack(self):
        if not self.first_shop_buffoon:
            self.first_shop_buffoon = True
            return self.D.centers['p_buffoon_normal_1']
        cume = 0
        for v in self.D.pool['Booster']:
            cume = cume + (v['weight'] or 1)
        poll = self.pseudorandom(self.pseudoseed('shop_pack' + str(self.ante))) * cume
        it = 0
        for v in self.D.pool['Booster']:
            it = it + (v['weight'] or 1)
            if it >= poll and it - (v['weight'] or 1) <= poll:
                return v
        return None

    def new_boss(self):
        a = self.ante
        elig = {}
        for k, v in self.D.blinds.items():
            b = v['boss']
            if not b: continue
            if not b['showdown'] and b['min'] <= max(1, a) and ((max(1, a) % 8 != 0) or a < 2):
                elig[k] = True
            elif b['showdown'] and a % 8 == 0 and a >= 2:
                elig[k] = True
        min_use = 100
        for k, v in self.bosses_used.items():
            if k in elig:
                elig[k] = v
                if v <= min_use: min_use = v
        keys = sorted(k for k, v in elig.items() if v <= min_use)
        k = keys[self.pick_index(len(keys), self.pseudoseed('boss')) - 1]
        self.bosses_used[k] += 1
        return k

    # ---------------- packs (Card:open - card.lua NOT provided: ASSUMED from vanilla) ---------
    def open_pack(self, booster):
        kind, n, ante = booster['kind'], int(booster['extra'] or 2), self.ante
        cards = []
        for i in range(n):
            if kind == 'Arcana':
                if 'v_omen_globe' in self.used_vouchers and self.pseudorandom('omen_globe') > 0.8:
                    c = self.create_card('Spectral', 'pack', soulable=True, append='ar2')
                else:
                    c = self.create_card('Tarot', 'pack', soulable=True, append='ar1')
            elif kind == 'Celestial':
                forced = None
                if 'v_telescope' in self.used_vouchers and i == 0:
                    if self.most_played:
                        forced = next(k for k, v in self.D.centers.items() if v['set'] == 'Planet' and v.get('hand_type') == self.most_played)
                    else:
                        self._warn('Telescope is owned but no most played hand is set: the first Celestial card is shown as a normal draw.')
                c = self.create_card('Planet', 'pack', soulable=True, forced_key=forced, append='pl1')
            elif kind == 'Spectral':
                c = self.create_card('Spectral', 'pack', soulable=True, append='spe')
            elif kind == 'Standard':
                typ = 'Enhanced' if self.pseudorandom(self.pseudoseed('stdset' + str(ante))) > 0.6 else 'Base'
                c = self.create_card(typ, 'pack', soulable=True, append='sta')
                ed = self.poll_edition('standard_edition' + str(ante), 2, True)
                if ed: c['edition'] = ed
                if self.pseudorandom(self.pseudoseed('stdseal' + str(ante))) > 1 - 0.02 * 10:
                    st = self.pseudorandom(self.pseudoseed('stdsealtype' + str(ante)))
                    c['seal'] = 'Red' if st > 0.75 else 'Blue' if st > 0.5 else 'Gold' if st > 0.25 else 'Purple'
            elif kind == 'Buffoon':
                c = self.create_card('Joker', 'pack', soulable=True, append='buf')
            else:
                raise ValueError(kind)
            cards.append(c)
        return cards

    def close_pack(self, booster, cards):
        """Player picks: The Soul first (if take_souls), then cards in the --take list; everything else is removed."""
        picks = int(booster.get('choose') or 1)
        taken = []
        for c in cards:
            if picks <= 0: break
            if c['key'] == 'c_soul' and self.take_souls and self._free_joker_slots() > 0:
                c['taken'] = True; picks -= 1; taken.append(c)
                c['soul_gives'] = self.use_soul()
        for c in cards:
            if picks <= 0: break
            if not c.get('taken') and c['key'] in self.take:
                if c['type'] == 'Joker':
                    if self._free_joker_slots() <= 0 and c.get('edition') != 'negative':
                        continue
                    c['taken'] = True; picks -= 1
                    self._gain_joker(c)
                else:
                    c['taken'] = True; picks -= 1
        for c in cards:
            if c['type'] == 'Joker' and c.get('taken'):
                continue
            self._removed(c['key'])

    def use_soul(self):
        """The Soul: create_card('Joker', G.jokers, true, nil,nil,nil,nil,'sou') (key_append 'sou' ASSUMED)."""
        leg = self.create_card('Joker', 'jokers', legendary=True, append='sou')
        self._gain_joker(leg)
        return leg

    def _warn(self, w):
        if w not in self.warnings:
            self.warnings.append(w)

    # ---------------- tags --------------------------------------------------------------------
    def add_tag(self, t, events):
        doubles = [i for i, x in enumerate(self.tags) if x == 'tag_double']
        copies = 0
        if t != 'tag_double':
            for i in reversed(doubles):           # every held Double Tag copies the new tag once
                del self.tags[i]; copies += 1
        self.tags.append(t)
        for _ in range(copies):
            self.tags.append(t)
            events.append(dict(event='double', tag=t))

    def blind_select(self, events):
        """Game:update_blind_select / skip: all 'immediate' tags, then the first 'new_blind_choice' tag."""
        i = 0
        while i < len(self.tags):
            t = self.tags[i]
            if TAG_TYPE.get(t) == 'immediate':
                del self.tags[i]
                ev = dict(event='tag', tag=t)
                if t == 'tag_top_up':                      # tag.lua not provided: 'top' key_append ASSUMED
                    made = []
                    for _ in range(2):
                        if self._free_joker_slots() > 0:
                            c = self.create_card('Joker', 'jokers', rarity=0, append='top')
                            self._gain_joker(c); made.append(c)
                    ev['cards'] = made
                events.append(ev)
                continue
            i += 1
        for i, t in enumerate(self.tags):
            if TAG_TYPE.get(t) == 'new_blind_choice':
                del self.tags[i]
                if t == 'tag_boss':
                    ev = dict(event='tag', tag=t, boss=self.new_boss())
                    self.cur_boss = ev['boss']
                    events.append(ev)
                else:
                    booster = self.D.centers[PACK_TAGS[t]]
                    ev = dict(event='tag_pack', tag=t, pack=booster)
                    if f"tagpack:{t}" in self.skip_packs:
                        ev['opened'] = False
                    else:
                        cards = self.open_pack(booster)
                        self.close_pack(booster, cards)
                        ev['opened'] = True; ev['cards'] = cards
                    events.append(ev)
                break

    # ---------------- one shop ----------------------------------------------------------------
    def shop(self, sid, game_ante):
        S = dict(id=sid, game_ante=game_ante, rng_ante=self.ante, label=SHOP_LABEL[sid[-1]])
        self.shop_cards = []
        for _ in range(self.joker_max):
            self.shop_cards.append(self.shop_slot())
        S['slots'] = [list(self.shop_cards)]
        vouchers = []
        if self.cur_voucher:
            vouchers.append(self.cur_voucher)
            self._created(self.cur_voucher)
        self.shop_voucher_keys = set(vouchers)
        packs = [self.get_pack(), self.get_pack()]
        for p in packs:
            self._created(p['key'])
        i = 0
        while i < len(self.tags):                 # Voucher Tag ('voucher_add')
            if TAG_TYPE.get(self.tags[i]) == 'voucher_add':
                del self.tags[i]
                v = self.next_voucher(from_tag=True)
                vouchers.append(v); self.shop_voucher_keys.add(v); self._created(v)
                continue
            i += 1
        S['vouchers'] = list(vouchers)
        # ---- player actions (in this order): buy vouchers, buy/take slot cards, reroll, open packs
        bought = []
        for v in vouchers:
            if v in self.buy_vouchers and v not in self.used_vouchers:
                bought.append(v)
                if v == self.cur_voucher:
                    self.cur_voucher = None
                before = len(self.shop_cards)
                self.redeem_voucher(v, in_shop=True)
                if len(self.shop_cards) > before:
                    S['slots'][-1] = list(self.shop_cards)
        S['bought_vouchers'] = bought
        self._take_from_slots()
        if self.preview_rerolls:
            snap = self._snapshot()
            prev = []
            for _ in range(self.preview_rerolls):
                prev.append(self._reroll())
            self._restore(snap)
            S['preview'] = prev
        for _ in range(self.rerolls.get(sid, 0)):
            S['slots'].append(self._reroll())
        S['packs'] = []
        for j, p in enumerate(packs):
            P = dict(pack=p)
            if f"{sid}.{j + 1}" in self.skip_packs:
                P['opened'] = False
            else:
                cards = self.open_pack(p)
                self.close_pack(p, cards)
                P['opened'] = True; P['cards'] = cards
            self._removed(p['key'])
            S['packs'].append(P)
        # leave shop: everything still in the shop is removed
        for c in self.shop_cards:
            if c and not c.get('taken'):
                self._removed(c['key'])
        for v in vouchers:
            self._removed(v)
        self.shop_cards = None
        self.shop_voucher_keys = set()
        return S

    def _take_from_slots(self):
        for c in self.shop_cards:
            if c and not c.get('taken') and c['key'] in self.take:
                if c['type'] == 'Joker':
                    if self._free_joker_slots() <= 0 and c.get('edition') != 'negative':
                        continue
                    self._gain_joker(c)
                c['taken'] = True

    def _reroll(self):
        """G.FUNCS.reroll_shop: remove remaining slot cards, then refill joker_max slots."""
        for c in self.shop_cards:
            if c and not c.get('taken'):
                self._removed(c['key'])
        self.shop_cards = [self.shop_slot() for _ in range(self.joker_max)]
        self._take_from_slots()
        return list(self.shop_cards)

    def _snapshot(self):
        import copy
        return copy.deepcopy({k: v for k, v in self.__dict__.items() if k not in ('D', 'rng')}), self.rng.u[:]

    def _restore(self, snap):
        d, u = snap
        self.__dict__.update(d)
        self.rng.u = u

    # ---------------- whole run ---------------------------------------------------------------
    def simulate(self, antes=3):
        out = []
        self.ante = 1
        self.cur_boss = self.new_boss()
        self.cur_voucher = self.next_voucher()
        cur_tags = [self.next_tag(), self.next_tag()]
        ev0 = []
        self.blind_select(ev0)
        for g in range(1, antes + 1):
            A = dict(ante=g, boss=self.cur_boss, tags=list(cur_tags), rounds=[])
            for kind, ti in (('s', 0), ('b', 1)):
                bid = shop_id(g, kind)
                if bid in self.skips:
                    ev = []
                    self.add_tag(cur_tags[ti], ev)
                    self.blind_select(ev)
                    A['rounds'].append(dict(blind=kind, skipped=True, tag=cur_tags[ti], events=ev))
                else:
                    S = self.shop(bid, g)
                    ev = []
                    self.blind_select(ev)
                    A['rounds'].append(dict(blind=kind, skipped=False, shop=S, events=ev))
            A['boss'] = self.cur_boss                     # (a Boss Tag may have rerolled it)
            # boss defeated -> ease_ante(1); new voucher + tags for the next ante; shop uses the NEW ante
            self.ante = g + 1
            self.cur_voucher = self.next_voucher()
            cur_tags = [self.next_tag(), self.next_tag()]
            S = self.shop(shop_id(g, 'x'), g)
            self.cur_boss = self.new_boss()
            ev = []
            self.blind_select(ev)
            A['rounds'].append(dict(blind='x', skipped=False, shop=S, events=ev))
            out.append(A)
        return out


def first_legendary(seed, data=None):
    """Mirror of misc_functions.get_first_legendary - the game's own seed->legendary prediction."""
    D = data or load_data()
    pool = D.rarity_pool[4]
    ps = pseudohash('Joker4' + seed.upper())
    ps = abs(float("%.13f" % ((2.134453429141 + ps * 1.72431234) % 1.0)))
    ps = (ps + pseudohash(seed.upper())) / 2
    rng = LuaRandom(); rng.seed(ps)
    return pool[rng.randint(len(pool)) - 1]['name']


# ---------------- name helpers shared by the CLIs ------------------------------------------
STAKES = ['White', 'Red', 'Green', 'Black', 'Blue', 'Purple', 'Orange', 'Gold']

def resolve(D, q, kinds=('centers', 'tags', 'blinds')):
    """In-game name or key -> key (case-insensitive; 'Deck'/'Tag' suffix optional)."""
    ql = q.strip().lower()
    for kind in kinds:
        src = getattr(D, kind)
        for k, v in src.items():
            n = (v.get('name') or '').lower()
            if ql in (k.lower(), n) or (n.endswith(' deck') and ql == n[:-5]) or (n.endswith(' tag') and ql == n[:-4]):
                return k
    raise ValueError(f"unknown item '{q}'")

def resolve_deck(D, q):
    q = q.strip().lower()
    for k, v in D.centers.items():
        if v['set'] == 'Back' and q in (k.lower(), v['name'].lower(), v['name'].lower().replace(' deck', ''), 'b_' + q):
            return k
    raise ValueError(f"unknown deck '{q}'")

def resolve_stake(q):
    q = str(q).strip().lower()
    if q.isdigit() and 1 <= int(q) <= 8:
        return int(q)
    for i, n in enumerate(STAKES, 1):
        if q in (n.lower(), n.lower() + ' stake', 'stake_' + n.lower()):
            return i
    raise ValueError(f"unknown stake '{q}' (1-8 or White..Gold)")

def item_name(D, k):
    for src in (D.centers, D.tags, D.blinds):
        if k in src:
            return src[k]['name']
    return k
