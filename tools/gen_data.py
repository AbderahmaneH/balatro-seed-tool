#!/usr/bin/env python3
"""Generates core_data.h (pools, names, key fragments) for the C/OpenCL core from game.lua.
Static pool exclusions are produced by the Python engine's own get_current_pool, so both share one source of truth."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repository root
sys.path.insert(0, os.path.join(ROOT, 'src'))
from engine import Run, load_data, TAG_TYPE, PACK_TAGS

# stream kinds: (name, prefix, suffix, has_ante). key = prefix + str(ante) + suffix  (or prefix alone)
KINDS = [
    ('CDT', 'cdt', '', 1), ('ILLUSION', 'illusion', '', 0),
    ('RARITY_SHO', 'rarity', 'sho', 1), ('JK1_SHO', 'Joker1sho', '', 1), ('JK2_SHO', 'Joker2sho', '', 1), ('JK3_SHO', 'Joker3sho', '', 1),
    ('EDI_SHO', 'edisho', '', 1),
    ('TAROT_SHO', 'Tarotsho', '', 1), ('PLANET_SHO', 'Planetsho', '', 1), ('SPECTRAL_SHO', 'Spectralsho', '', 1),
    ('ENH_SHO', 'Enhancedsho', '', 1), ('FRONT_SHO', 'frontsho', '', 1),
    ('RARITY_BUF', 'rarity', 'buf', 1), ('JK1_BUF', 'Joker1buf', '', 1), ('JK2_BUF', 'Joker2buf', '', 1), ('JK3_BUF', 'Joker3buf', '', 1),
    ('EDI_BUF', 'edibuf', '', 1),
    ('JK2_UTA', 'Joker2uta', '', 1), ('EDI_UTA', 'ediuta', '', 1), ('JK3_RTA', 'Joker3rta', '', 1), ('EDI_RTA', 'edirta', '', 1),
    ('JK1_TOP', 'Joker1top', '', 1), ('EDI_TOP', 'editop', '', 1),
    ('SHOP_PACK', 'shop_pack', '', 1), ('VOUCHER', 'Voucher', '', 1), ('VOUCHER_TAG', 'Voucher_fromtag', '', 0),
    ('TAG', 'Tag', '', 1), ('BOSS', 'boss', '', 0),
    ('LEGEND', 'Joker4', '', 0), ('EDI_SOU', 'edisou', '', 1),
    ('SOUL_TAROT', 'soul_Tarot', '', 1), ('SOUL_SPECTRAL', 'soul_Spectral', '', 1), ('SOUL_PLANET', 'soul_Planet', '', 1),
    ('TAROT', 'Tarotar1', '', 1), ('PLANET', 'Planetpl1', '', 1), ('SPECTRAL', 'Spectralspe', '', 1),
    ('OMEN', 'omen_globe', '', 0), ('SPECTRAL_AR2', 'Spectralar2', '', 1),
    ('STDSET', 'stdset', '', 1), ('ENH', 'Enhancedsta', '', 1), ('FRONT', 'frontsta', '', 1),
    ('EDI_STD', 'standard_edition', '', 1), ('STDSEAL', 'stdseal', '', 1), ('STDSEALTYPE', 'stdsealtype', '', 1),
]
TAGTYPE_CODE = {'store_joker_create': 1, 'store_joker_modify': 2, 'voucher_add': 3, 'new_blind_choice': 4,
                'immediate': 5, 'tag_add': 6}

def main(out):
    D = load_data()
    names, idx = [], {}
    def item(key, name):
        idx[key] = len(names); names.append((key, name))
    for k in sorted(D.centers): item(k, D.centers[k]['name'] or k)
    for k in sorted(D.tags): item(k, D.tags[k]['name'])
    for k in sorted(D.blinds): item(k, D.blinds[k]['name'])

    pools = []
    def add_pool(cname, lst):
        pools.append((cname, [idx[x] if x != 'UNAVAILABLE' else -1 for x in lst]))

    for m, mode in enumerate(('all', 'fresh')):
        r = Run('AAAAAAAA', D, unlocked=mode)
        for rar, roll in ((1, 0.0), (2, 0.8), (3, 0.99)):
            add_pool(f'JOKER_R{rar}_M{m}', r.get_current_pool('Joker', roll, False, 'x')[0])
        add_pool(f'JOKER_R4_M{m}', r.get_current_pool('Joker', None, True, 'sou')[0])
        # vouchers: static part only (unlock); requires / used / shop checks are dynamic in C
        add_pool(f'VOUCHER_M{m}', [v['key'] if r._unlock_ok(v) else 'UNAVAILABLE' for v in D.pool['Voucher']])
        for ac, ante in ((0, 1), (1, 2)):
            r.ante = ante
            add_pool(f'TAG_M{m}_A{ac}', r.get_current_pool('Tag')[0])
        r.ante = 1
    for played in (0, 1):
        r = Run('AAAAAAAA', D, planets_played=bool(played))
        add_pool(f'PLANET_P{played}', r.get_current_pool('Planet')[0])
    r = Run('AAAAAAAA', D)
    add_pool('TAROT', r.get_current_pool('Tarot')[0])
    add_pool('SPECTRAL', r.get_current_pool('Spectral')[0])
    add_pool('ENHANCED', r.get_current_pool('Enhanced')[0])
    pools.append(('CARDS', list(range(len(D.card_keys_sorted)))))

    flat, offs, lens = [], [], []
    for cname, lst in pools:
        offs.append(len(flat)); lens.append(len(lst)); flat.extend(lst)

    boosters = D.pool['Booster']
    KCODE = {'Arcana': 0, 'Celestial': 1, 'Standard': 2, 'Buffoon': 4, 'Spectral': 5}
    bl = sorted(D.blinds.items())
    vreq = [-1] * len(names)
    for v in D.pool['Voucher']:
        if v['requires']:
            vreq[idx[v['key']]] = idx[v['requires'][0]]
    tagtype = [0] * len(names)
    for t, ty in TAG_TYPE.items():
        tagtype[idx[t]] = TAGTYPE_CODE.get(ty, 0)
    bidx = {b['key']: i for i, b in enumerate(boosters)}
    tagpack = [-1] * len(names)
    for t, p in PACK_TAGS.items():
        tagpack[idx[t]] = bidx[p]

    kindcode = {'Joker': 1, 'Tarot': 2, 'Planet': 3, 'Spectral': 4, 'Enhanced': 5, 'Voucher': 6, 'Booster': 7}
    item_kind, item_group = [], []
    first_by_name = {}
    for key, nm in names:
        c = D.centers.get(key)
        item_kind.append(kindcode.get(c['set'], 0) if c else 0)
        if c and c['set'] == 'Booster':
            first_by_name.setdefault(nm, idx[key])
            item_group.append(first_by_name[nm])
        else:
            item_group.append(idx[key])
    L = []
    w = L.append
    w('/* AUTO-GENERATED by gen_data.py from game.lua - do not edit */')
    w(f'#define N_ITEMS {len(names)}')
    w(f'#define N_WORDS {(len(names) + 31) // 32}')
    for i, (cname, _) in enumerate(pools):
        w(f'#define PID_{cname} {i}')
    w(f'#define N_POOLS {len(pools)}')
    for i, (kn, pre, post, ha) in enumerate(KINDS):
        w(f'#define K_{kn} {i}')
    w(f'#define N_KINDS {len(KINDS)}')
    w(f'#define N_BOOSTERS {len(boosters)}')
    w(f'#define N_BLINDS {len(bl)}')
    w(f'#define N_CARDS {len(D.card_keys_sorted)}')
    for key, i in idx.items():
        w(f'#define ID_{key.upper()} {i}')
    w(f'#define BOOSTER_BUFFOON_NORMAL_1 {bidx["p_buffoon_normal_1"]}')
    w('CONSTANT int POOL_FLAT[] = {' + ','.join(map(str, flat)) + '};')
    w('CONSTANT int POOL_OFF[] = {' + ','.join(map(str, offs)) + '};')
    w('CONSTANT int POOL_LEN[] = {' + ','.join(map(str, lens)) + '};')
    w('CONSTANT int BOOST_ID[] = {' + ','.join(str(idx[b['key']]) for b in boosters) + '};')
    w('CONSTANT double BOOST_W[] = {' + ','.join(repr(float(b['weight'] or 1)) for b in boosters) + '};')
    w('CONSTANT int BOOST_KIND[] = {' + ','.join(str(KCODE[b['kind']]) for b in boosters) + '};  /* 0 arcana 1 celestial 2 standard 4 buffoon 5 spectral */')
    w('CONSTANT int BOOST_N[] = {' + ','.join(str(int(b['extra'])) for b in boosters) + '};')
    w('CONSTANT int BOOST_CHOOSE[] = {' + ','.join(str(int(b['choose'] or 1)) for b in boosters) + '};')
    w('CONSTANT int BLIND_ID[] = {' + ','.join(str(idx[k]) for k, v in bl) + '};')
    w('CONSTANT int BLIND_BOSS[] = {' + ','.join('1' if v['boss'] else '0' for k, v in bl) + '};')
    w('CONSTANT int BLIND_MIN[] = {' + ','.join(str(v['boss']['min'] if v['boss'] else 0) for k, v in bl) + '};')
    w('CONSTANT int BLIND_SHOW[] = {' + ','.join('1' if (v['boss'] and v['boss']['showdown']) else '0' for k, v in bl) + '};')
    w('CONSTANT int ITEM_KIND[] = {' + ','.join(map(str, item_kind)) + '};  /* 1 joker 2 tarot 3 planet 4 spectral 5 enhanced 6 voucher 7 booster */')
    w('CONSTANT int ITEM_GROUP[] = {' + ','.join(map(str, item_group)) + '};')
    w('CONSTANT int ITEM_RARITY[] = {' + ','.join(str((D.centers[k].get('rarity') or 0) if k in D.centers and D.centers[k]['set'] == 'Joker' else 0) for k, n in names) + '};')
    w('CONSTANT int VREQ[] = {' + ','.join(map(str, vreq)) + '};')
    w('CONSTANT int TAGTYPE[] = {' + ','.join(map(str, tagtype)) + '};')
    w('CONSTANT int TAGPACK[] = {' + ','.join(map(str, tagpack)) + '};')
    blob, po, pl, so, sl, ha = bytearray(), [], [], [], [], []
    for kn, pre, post, h in KINDS:
        po.append(len(blob)); pl.append(len(pre)); blob += pre.encode()
        so.append(len(blob)); sl.append(len(post)); blob += post.encode(); ha.append(h)
    w('CONSTANT unsigned char KEY_BLOB[] = {' + ','.join(map(str, blob)) + '};')
    w('CONSTANT int KEY_PRE_OFF[] = {' + ','.join(map(str, po)) + '};')
    w('CONSTANT int KEY_PRE_LEN[] = {' + ','.join(map(str, pl)) + '};')
    w('CONSTANT int KEY_POST_OFF[] = {' + ','.join(map(str, so)) + '};')
    w('CONSTANT int KEY_POST_LEN[] = {' + ','.join(map(str, sl)) + '};')
    w('CONSTANT int KEY_HAS_ANTE[] = {' + ','.join(map(str, ha)) + '};')
    w('#ifdef WITH_NAMES')
    w('static const char *ITEM_KEY[] = {' + ','.join('"%s"' % k for k, n in names) + '};')
    w('static const char *CARD_KEY[] = {' + ','.join('"%s"' % k for k in D.card_keys_sorted) + '};')
    w('#endif')
    open(out, 'w').write('\n'.join(L) + '\n')
    print('wrote', out, 'items', len(names), 'pools', len(pools))

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'src', 'core_data.h'))
