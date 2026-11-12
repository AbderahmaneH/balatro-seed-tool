"""Search jobs shared by find_seeds.py (command line) and app.py (UI).
Seeds can be 1-8 characters; the seed space for a length range is ordered shortest first (shortlex):
index 0 = "1", 33 = "Z", 34 = "11", ...  All engines enumerate the same order."""
import os, random, shutil, subprocess, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from engine import SEED_CHARS, item_name
from bridge import build_cfg, py_check, item_index, C_LOCS

# ------------------------------------------------------------------ seed space
def space_size(lmin, lmax):
    return sum(34 ** L for L in range(lmin, lmax + 1))

def idx2seed(n, lmin=8, lmax=8):
    L = lmin
    while L < lmax and n >= 34 ** L:
        n -= 34 ** L; L += 1
    s = []
    for _ in range(L):
        s.append(SEED_CHARS[n % 34]); n //= 34
    return ''.join(reversed(s))

def seed2idx(s, lmin=8, lmax=8):
    s = s.upper()
    if not (lmin <= len(s) <= lmax):
        raise ValueError(f"seed '{s}' is not {lmin}-{lmax} characters long")
    n = sum(34 ** L for L in range(lmin, len(s)))
    v = 0
    for ch in s:
        v = v * 34 + SEED_CHARS.index(ch)
    return n + v

def parse_lengths(s):
    s = str(s).strip()
    if '-' in s:
        a, b = (int(x) for x in s.split('-'))
    else:
        a = b = int(s)
    if not (1 <= a <= b <= 8):
        raise ValueError('seed length must be within 1-8, e.g. 8 or 1-8')
    return a, b

# ------------------------------------------------------------------ engines
def build_cpu():
    exe = os.path.join(HERE, 'bsearch' + ('.exe' if os.name == 'nt' else ''))
    srcs = [os.path.join(HERE, f) for f in ('search.c', 'core.h', 'core_data.h')]
    if os.path.exists(exe) and os.path.getmtime(exe) >= max(os.path.getmtime(s) for s in srcs):
        return exe
    cc = shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
    if not cc:
        return None
    for extra in (['-fopenmp'], []):
        cmd = [cc, '-O2', '-ffp-contract=off'] + extra + [os.path.join(HERE, 'search.c'), '-o', exe, '-lm']
        if subprocess.run(cmd, capture_output=True, cwd=HERE).returncode == 0:
            return exe
    return None

def gpu_available():
    try:
        import pyopencl as cl  # noqa
        return any('cl_khr_fp64' in d.extensions for p in cl.get_platforms() for d in p.get_devices())
    except Exception:
        return False

def run_cpu_raw(exe, cfg, crits, antes, start, count, rnd, hits, threads, lens=(8, 8), proc_holder=None):
    cmd = [exe, '--cfg', ','.join(map(str, cfg)), '--antes', str(antes), '--hits', str(hits),
           '--start', str(start), '--count', str(count), '--lens', f'{lens[0]},{lens[1]}']
    for c in crits:
        cmd += ['--crit', ','.join(map(str, c.ints()))]
    if rnd is not None: cmd += ['--random', str(rnd)]
    if threads: cmd += ['--threads', str(threads)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc_holder is not None:
        proc_holder.append(p)
    out, err = p.communicate()
    if p.returncode not in (0, -15, -9, 1) and err:
        raise RuntimeError(err.strip())
    return [ln.split()[0] for ln in out.splitlines() if ln.strip()]

# ------------------------------------------------------------------ describing a hit
KIND = {0: 'after Small Blind', 1: 'after Big Blind', 2: 'after Boss Blind', 3: 'from a tag'}

def describe(D, where, crit, names, cards, limit=4):
    out = []
    for loc, g, kind, rr, iid, ed, seal, card in where[:limit]:
        nm = names.get(iid, '?')
        if card >= 0:
            nm = cards[card] + ('' if names.get(iid) in (None, 'Default Base') else f" {names[iid]}")
        tags = []
        if ed: tags.append(['', 'Foil', 'Holo', 'Polychrome', 'Negative'][ed])
        if seal: tags.append(['', 'Red', 'Blue', 'Gold', 'Purple'][seal] + ' Seal')
        if tags: nm += ' (' + ', '.join(tags) + ')'
        sh = KIND[kind] if kind != 3 else ''
        if loc == 0: place = f"shop slot, ante {g} {sh}" + (f", after {rr} reroll{'s' if rr > 1 else ''}" if rr else '')
        elif loc == 1: place = f"pack, ante {g} {sh}" if kind != 3 else f"pack from a skip tag, ante {g}"
        elif loc == 5: place = f"from The Soul, ante {g} {sh}" if kind != 3 else f"from The Soul in a tag pack, ante {g}"
        elif loc == 7: place = f"Top-up Tag, ante {g}"
        elif loc == 2: place = f"voucher, ante {g} {sh}"
        elif loc == 6: place = f"booster in shop, ante {g} {sh}"
        elif loc == 3: place = f"skip tag, ante {g}"
        else: place = f"boss, ante {g}"
        out.append(f"{nm} [{place.strip()}]")
    if len(where) > limit:
        out.append(f"+{len(where) - limit} more")
    return '; '.join(out)

# ------------------------------------------------------------------ the job
class SearchJob:
    def __init__(self, D, opts, crits, engine='auto', count=20_000_000, start=0, rnd=None, lens=(1, 8),
                 hits=10, threads=0):
        self.D, self.opts, self.crits = D, opts, crits
        self.engine, self.count, self.start, self.rnd, self.lens = engine, count, start, rnd, lens
        self.max_hits, self.threads = hits, threads
        self.antes = max(c.hi for c in crits)
        self.space = space_size(*lens)
        self.scanned = 0
        self.results = []          # dicts: seed, desc[list]
        self.rejected = 0
        self.state = 'starting'
        self.message = ''
        self.engine_used = None
        self.t0 = None
        self.t_end = None
        self._stop = threading.Event()
        self._procs = []
        self._seen = set()
        idx = item_index(D)
        self.names = {i: item_name(D, k) for k, i in idx.items()}
        self.cards = [D.cards[k]['name'] for k in D.card_keys_sorted]

    # public ------------------------------------------------------------
    def stop(self):
        self._stop.set()
        for p in self._procs:
            try: p.terminate()
            except Exception: pass

    def elapsed(self):
        if not self.t0: return 0.0
        return (self.t_end or time.time()) - self.t0

    def status(self):
        el = self.elapsed()
        return dict(state=self.state, message=self.message, engine=self.engine_used, scanned=self.scanned,
                    total=min(self.count, self.space) if self.rnd is None else self.count,
                    rate=self.scanned / el if el > 0 else 0, elapsed=el, results=self.results,
                    rejected=self.rejected, space=self.space)

    def run(self):
        self.t0 = time.time()
        try:
            self._run()
            if self.state == 'running':
                self.state = 'done'
        except Exception as e:  # report to the UI instead of dying silently
            self.state = 'error'
            self.message = str(e)
        self.t_end = time.time()

    def start_thread(self):
        th = threading.Thread(target=self.run, daemon=True)
        th.start()
        return th

    # internals ---------------------------------------------------------
    def _accept(self, seed):
        if seed in self._seen or len(self.results) >= self.max_hits:
            return
        self._seen.add(seed)
        ok, where, _ = py_check(seed, self.D, self.opts, self.crits, detail=True)
        if not ok:
            self.rejected += 1
            return
        self.results.append(dict(seed=seed, desc=[describe(self.D, where[i], c, self.names, self.cards)
                                                   for i, c in enumerate(self.crits)]))

    def _done(self):
        return self._stop.is_set() or len(self.results) >= self.max_hits

    def _run(self):
        eng = self.engine
        exe = None
        if eng in ('auto', 'cpu'):
            exe = build_cpu()
            if eng == 'cpu' and not exe:
                raise RuntimeError('No C compiler (gcc/clang) found - choose the GPU or Python engine')
        if eng == 'auto':
            eng = 'cpu' if exe else 'py'
        self.engine_used = eng
        self.state = 'running'
        total = min(self.count, self.space - self.start) if self.rnd is None else self.count
        if total <= 0:
            self.message = 'start is beyond the end of the seed space'
            return
        cfg = build_cfg(self.D, self.opts)
        if eng == 'cpu':
            chunk, k = 100_000, 0
            while self.scanned < total and not self._done():
                n = min(chunk, total - self.scanned)
                t = time.time()
                cand = run_cpu_raw(exe, cfg, self.crits, self.antes, self.start + self.scanned, n,
                                   None if self.rnd is None else self.rnd * 1000003 + k,
                                   self.max_hits * 3 + 5, self.threads, self.lens, self._procs)
                self._procs.clear()
                if self._stop.is_set():
                    break
                self.scanned += n; k += 1
                if self.rnd is None:
                    cand.sort(key=lambda x: seed2idx(x, *self.lens))
                for s in cand:
                    self._accept(s)
                dt = time.time() - t
                if dt < 0.7: chunk = min(chunk * 2, 50_000_000)
                elif dt > 2.5: chunk = max(chunk // 2, 20_000)
        elif eng == 'gpu':
            import gpu_search
            if self.rnd is not None:
                self.message = 'GPU engine scans sequentially; random sampling ignored'
            chunk = 1 << 22
            while self.scanned < total and not self._done():
                n = min(chunk, total - self.scanned)
                cand, done, _, dev = gpu_search.search_range(cfg, self.crits, self.antes, self.start + self.scanned, n,
                                                             maxhits=self.max_hits * 3 + 5, quiet=True, lens=self.lens)
                self.engine_used = f'gpu ({dev})'
                self.scanned += done
                for s in cand:
                    self._accept(s)
        else:
            rng = random.Random(self.rnd) if self.rnd is not None else None
            while self.scanned < total and not self._done():
                idx = rng.randrange(self.space) if rng else self.start + self.scanned
                s = idx2seed(idx, *self.lens)
                self.scanned += 1
                if py_check(s, self.D, self.opts, self.crits):
                    self._accept(s)
        if self._stop.is_set():
            self.state = 'stopped'
