#!/usr/bin/env python3
"""
Balatro Seed Tool - local app.   python app.py          (opens http://127.0.0.1:8777 in your browser)

Only the Python standard library is needed. The fast finder engine is compiled automatically when gcc/clang
is installed; the GPU engine is used when pyopencl is installed. Everything runs on your own computer.
Options:  --port N   --no-browser   --host 0.0.0.0 (to open it from your phone on the same Wi-Fi)
"""
import argparse, json, os, sys, threading, time, uuid, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from engine import (Run, load_data, valid_seed, first_legendary, SHOP_LABEL, STAKES, item_name, parse_shop_id)
from bridge import parse_crit
import searcher

D = load_data()
JOBS = {}
ENGINES = {}

# ------------------------------------------------------------------ metadata for the UI
def meta():
    C = D.centers
    def lst(setname, extra=None):
        out = [dict(key=k, name=v['name'], **(extra(v) if extra else {})) for k, v in C.items() if v['set'] == setname]
        return sorted(out, key=lambda x: x['name'])
    packs, seen = [], set()
    for b in D.pool['Booster']:
        if b['name'] not in seen:
            seen.add(b['name']); packs.append(dict(key=b['key'], name=b['name'], kind=b['kind']))
    hands = sorted({v['hand_type'] for v in C.values() if v['set'] == 'Planet' and v.get('hand_type')})
    if 'cpu' not in ENGINES:
        ENGINES['cpu'] = bool(searcher.build_cpu())
        ENGINES['gpu'] = searcher.gpu_available()
    return dict(
        decks=[dict(key=v['key'], name=v['name']) for v in sorted((v for v in C.values() if v['set'] == 'Back' and v['key'] != 'b_challenge'), key=lambda v: v['order'])],
        stakes=STAKES,
        jokers=lst('Joker', lambda v: dict(rarity=v['rarity'])),
        tarots=lst('Tarot'), planets=lst('Planet'), spectrals=lst('Spectral'),
        vouchers=lst('Voucher', lambda v: dict(requires=v['requires'][0] if v['requires'] else None)),
        enhancements=lst('Enhanced'),
        tags=sorted([dict(key=k, name=v['name']) for k, v in D.tags.items()], key=lambda x: x['name']),
        bosses=sorted([dict(key=k, name=v['name'], showdown=v['boss']['showdown']) for k, v in D.blinds.items() if v['boss']], key=lambda x: x['name']),
        packs=packs, hands=hands, cards=[D.cards[k]['name'] for k in D.card_keys_sorted],
        engines=dict(cpu=ENGINES['cpu'], gpu=ENGINES['gpu'], py=True, threads=os.cpu_count() or 1),
        space={str(L): 34 ** L for L in range(1, 9)})

# ------------------------------------------------------------------ options from the UI
def opts_from(o):
    o = o or {}
    def keys(name, kind=('centers',)):
        out = []
        for k in o.get(name) or []:
            if k in D.centers or k in D.tags:
                out.append(k)
        return out
    rer = {}
    for sid, n in (o.get('rerolls') or {}).items():
        if int(n) > 0:
            rer[parse_shop_id(sid)] = int(n)
    return dict(unlocked='fresh' if o.get('unlocked') == 'fresh' else 'all',
                deck=o.get('deck') if o.get('deck') in D.centers else 'b_red',
                stake=max(1, min(8, int(o.get('stake') or 1))),
                planets_played=bool(o.get('planets_played')),
                locked=keys('locked'), own=keys('own'), buy_vouchers=keys('buy_vouchers'), take=keys('take'),
                take_souls=o.get('take_souls', True) is not False,
                most_played=o.get('most_played') or None,
                skips={parse_shop_id(x) for x in o.get('skips') or [] if not parse_shop_id(x).endswith('x')},
                rerolls=rer, skip_packs=set(o.get('skip_packs') or []),
                start_consumables='used' if o.get('start_consumables') == 'used' else 'held')

# ------------------------------------------------------------------ analysis -> view model
def card_vm(c):
    if c is None:
        return None
    k = c['key']
    cen = D.centers.get(k, {})
    t = c['type']
    vm = dict(key=k, name=c['name'])
    if k == 'c_soul': vm['kind'] = 'soul'
    elif k == 'c_black_hole': vm['kind'] = 'blackhole'
    elif t == 'Joker': vm['kind'] = 'joker'; vm['rarity'] = cen.get('rarity')
    elif t in ('Base', 'Enhanced'):
        vm['kind'] = 'card'; vm['name'] = c.get('card', c['name'])
        if k != 'c_base': vm['enh'] = c['name']
    else: vm['kind'] = t.lower()
    for f in ('edition', 'seal', 'sticker', 'rental', 'taken', 'from_tag'):
        if c.get(f): vm[f] = c[f]
    if 'soul_gives' in c:
        L = c['soul_gives']
        vm['legendary'] = dict(key=L['key'], name=L['name'], edition=L.get('edition'))
    return vm

def analyze(req):
    seed = (req.get('seed') or '').strip().upper()
    if not valid_seed(seed):
        raise ValueError('A seed is 1 to 8 characters from 1-9, A-N and P-Z (no 0 or O).')
    antes = max(1, min(int(req.get('antes') or 3), 39))
    o = opts_from(req.get('opts'))
    run = Run(seed, D, preview_rerolls=max(0, min(int(req.get('preview') or 0), 20)), **o)
    T = run.simulate(antes)
    legs, antes_vm = [], []
    for A in T:
        g = A['ante']
        rounds = []
        for R in A['rounds']:
            rv = dict(blind=R['blind'], skipped=bool(R.get('skipped')))
            if R.get('skipped'):
                rv['tag'] = dict(key=R['tag'], name=D.tags[R['tag']]['name'])
            else:
                S = R['shop']
                rv['shop'] = dict(id=S['id'], rng_ante=S['rng_ante'],
                                  vouchers=[dict(key=v, name=item_name(D, v), bought=v in S['bought_vouchers']) for v in S['vouchers']],
                                  slots=[[card_vm(c) for c in pair] for pair in S['slots']],
                                  preview=[[card_vm(c) for c in pair] for pair in S.get('preview', [])],
                                  packs=[dict(key=P['pack']['key'], name=P['pack']['name'], kind=P['pack']['kind'],
                                              choose=P['pack'].get('choose') or 1, size=P['pack']['extra'], opened=P['opened'],
                                              id=f"{S['id']}.{j + 1}",
                                              cards=[card_vm(c) for c in P.get('cards', [])]) for j, P in enumerate(S['packs'])])
                for P in rv['shop']['packs']:
                    for c in P['cards']:
                        if c and c.get('legendary'):
                            legs.append(dict(ante=g, where=f"shop {SHOP_LABEL[R['blind']]}", pack=P['name'], **c['legendary']))
            evs = []
            for e in R.get('events', []):
                ev = dict(event=e['event'], tag=dict(key=e['tag'], name=D.tags[e['tag']]['name']))
                if e.get('boss'): ev['boss'] = dict(key=e['boss'], name=D.blinds[e['boss']]['name'])
                if e['event'] == 'tag_pack':
                    ev['pack'] = dict(key=e['pack']['key'], name=e['pack']['name'], kind=e['pack']['kind'])
                    ev['opened'] = e.get('opened', False)
                if e.get('cards'):
                    ev['cards'] = [card_vm(c) for c in e['cards']]
                    for c in ev['cards']:
                        if c and c.get('legendary'):
                            legs.append(dict(ante=g, where=f"{ev['tag']['name']}", pack=ev.get('pack', {}).get('name', ''), **c['legendary']))
                evs.append(ev)
            rv['events'] = evs
            rounds.append(rv)
        antes_vm.append(dict(ante=g, boss=dict(key=A['boss'], name=D.blinds[A['boss']]['name']),
                             tags=[dict(key=t, name=D.tags[t]['name']) for t in A['tags']], rounds=rounds))
    return dict(seed=seed, deck=D.centers[run.deck]['name'], stake=STAKES[run.stake - 1],
                first_legendary=first_legendary(seed, D), legendaries=legs, antes=antes_vm, warnings=run.warnings)

def export(req):
    import analyze as A
    seed = (req.get('seed') or '').strip().upper()
    if not valid_seed(seed):
        raise ValueError('invalid seed')
    fmt = req.get('format') if req.get('format') in ('text', 'md', 'json') else 'md'
    run = Run(seed, D, preview_rerolls=int(req.get('preview') or 0), **opts_from(req.get('opts')))
    T = run.simulate(max(1, min(int(req.get('antes') or 3), 39)))
    return A.to_json(D, run, T) if fmt == 'json' else A.render(D, None, run, T, fmt)

# ------------------------------------------------------------------ search jobs
def start_search(req):
    crits = [parse_crit(D, s) for s in req.get('crits') or []]
    if not crits:
        raise ValueError('Add at least one condition.')
    if len(crits) > 16:
        raise ValueError('At most 16 conditions.')
    lens = searcher.parse_lengths(req.get('lengths') or '1-8')
    start = 0
    if req.get('from'):
        f = req['from'].strip().upper()
        if not valid_seed(f):
            raise ValueError('"Start from" must be a valid seed.')
        start = searcher.seed2idx(f, *lens)
    rnd = int(req['random']) if req.get('random') not in (None, '', False) else None
    job = searcher.SearchJob(D, opts_from(req.get('opts')), crits, req.get('engine') or 'auto',
                             max(1, int(req.get('count') or 20_000_000)), start, rnd, lens,
                             max(1, min(int(req.get('hits') or 20), 500)), int(req.get('threads') or 0))
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = job
    job.start_thread()
    return dict(id=jid, space=job.space)

# ------------------------------------------------------------------ HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        # lets "Balatro Seed Tool.html" opened from your disk use this local app's fast engines
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            import build_ui
            return self._send(200, build_ui.page(), 'text/html; charset=utf-8')
        if u.path == '/api/meta':
            return self._send(200, meta())
        if u.path == '/api/job':
            jid = parse_qs(u.query).get('id', [''])[0]
            j = JOBS.get(jid)
            return self._send(200, j.status()) if j else self._send(404, dict(error='no such search'))
        if u.path in ('/guide.pdf', '/guide.md'):
            p = os.path.join(ROOT, 'docs', 'GUIDE' + u.path[6:])
            if os.path.exists(p):
                return self._send(200, open(p, 'rb').read(), 'application/pdf' if p.endswith('pdf') else 'text/markdown; charset=utf-8')
        return self._send(404, dict(error='not found'))

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get('Content-Length') or 0)
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
            if u.path == '/api/analyze':
                return self._send(200, analyze(req))
            if u.path == '/api/export':
                return self._send(200, export(req), 'text/plain; charset=utf-8')
            if u.path == '/api/search':
                return self._send(200, start_search(req))
            if u.path == '/api/stop':
                j = JOBS.get(req.get('id'))
                if j: j.stop()
                return self._send(200, dict(ok=True))
            return self._send(404, dict(error='not found'))
        except (ValueError, KeyError) as e:
            return self._send(400, dict(error=str(e).strip("'")))
        except Exception as e:
            return self._send(500, dict(error=f'{type(e).__name__}: {e}'))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8777)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    threading.Thread(target=meta, daemon=True).start()       # compile the C engine in the background
    srv = ThreadingHTTPServer((a.host, a.port), H)
    url = f'http://{"127.0.0.1" if a.host == "0.0.0.0" else a.host}:{a.port}/'
    print(f'Balatro Seed Tool running at {url}   (Ctrl+C to quit)')
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('bye')

if __name__ == '__main__':
    main()
