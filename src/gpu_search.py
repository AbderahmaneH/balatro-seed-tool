#!/usr/bin/env python3
"""
OpenCL (GPU) back-end for find_seeds.py.        pip install pyopencl numpy

!! Written without access to a GPU: the kernel is the same core.h that is tested on the CPU and it compiles
!! as OpenCL C 1.2, but it has never been executed.  Run the self-test first:

      python gpu_search.py --selftest       (GPU vs CPU/Python on the same seeds; must print PASSED)
      python gpu_search.py --bench          (real speed on your card)

Every GPU hit is re-verified by the Python engine in find_seeds.py, so a broken kernel can only miss seeds.
The algorithm needs double precision; GeForce cards run fp64 at 1/64 speed, so an RTX 3050 may not beat a
good multi-core CPU.  Measure before relying on it.
"""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

KERNEL = r"""
__constant uchar CHARSET[34] = {'1','2','3','4','5','6','7','8','9','A','B','C','D','E','F','G','H','I','J','K','L','M','N','P','Q','R','S','T','U','V','W','X','Y','Z'};

__kernel void search(ulong first, __constant int *cfg, __constant Crit *cr, int ncr, int antes,
                     __global uchar *hits, __global volatile int *nhits, int maxhits, int lmin, int lmax)
{
    ulong n = first + (ulong)get_global_id(0);
    uchar s[8];
    int i, r, L = lmin;
    ulong p = 1;
    for (i = 0; i < L; i++) p *= 34;
    while (L < lmax && n >= p) { n -= p; L++; p *= 34; }       /* shortlex: shorter seeds first */
    if (n >= p) return;                                          /* beyond the seed space */
    for (i = L - 1; i >= 0; i--) { s[i] = CHARSET[n % 34]; n /= 34; }
    Run R;
    run_init(&R, s, L, cfg, cr, ncr);
    r = simulate(&R, antes);
    if (r) {
        int k = atomic_inc(nhits);
        if (k < maxhits) for (i = 0; i < 8; i++) hits[k * 8 + i] = i < L ? s[i] : 0;
    }
}
"""

def source():
    data = open(os.path.join(HERE, 'core_data.h')).read()
    core = open(os.path.join(HERE, 'core.h')).read().replace('#include "core_data.h"', data)
    return '#define BALATRO_OPENCL 1\n' + core + KERNEL

def _context():
    import pyopencl as cl
    best = None
    for p in cl.get_platforms():
        for d in p.get_devices():
            fp64 = 'cl_khr_fp64' in d.extensions
            score = (100 if fp64 else 0) + (10 if d.type & cl.device_type.GPU else 0)
            if best is None or score > best[0]:
                best = (score, d)
    if best is None:
        raise SystemExit('No OpenCL device found (install the GPU driver; NVIDIA drivers include OpenCL).')
    d = best[1]
    if 'cl_khr_fp64' not in d.extensions:
        raise SystemExit(f'OpenCL device "{d.name}" lacks double precision (cl_khr_fp64), which the algorithm needs.')
    return cl.Context([d]), d

_PROG = {}
def search_range(cfg, crits, antes, start, count, maxhits=1000, quiet=False, lens=(8, 8)):
    """cfg: list of ints (bridge.build_cfg), crits: list of bridge.Crit. Returns (seeds, scanned, seconds, device)."""
    import numpy as np
    import pyopencl as cl
    if 'ctx' not in _PROG:
        ctx, dev = _context()
        prog = cl.Program(ctx, source()).build(options=['-cl-std=CL1.2'])
        _PROG.update(ctx=ctx, dev=dev, prog=prog, q=cl.CommandQueue(ctx))
    ctx, dev, prog, q = _PROG['ctx'], _PROG['dev'], _PROG['prog'], _PROG['q']
    mf = cl.mem_flags
    cfg_buf = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.array(cfg, dtype=np.int32))
    cr = np.array([x for c in crits for x in c.ints()], dtype=np.int32)
    cr_buf = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=cr)
    hits_buf = cl.Buffer(ctx, mf.READ_WRITE, size=maxhits * 8)
    nh = np.zeros(1, dtype=np.int32)
    nh_buf = cl.Buffer(ctx, mf.READ_WRITE | mf.COPY_HOST_PTR, hostbuf=nh)
    chunk, done, found, t0 = 1 << 20, 0, [], time.time()
    while done < count and len(found) < maxhits:
        n = min(chunk, count - done)
        prog.search(q, (n,), None, np.uint64(start + done), cfg_buf, cr_buf, np.int32(len(crits)), np.int32(antes),
                    hits_buf, nh_buf, np.int32(maxhits), np.int32(lens[0]), np.int32(lens[1]))
        q.finish()
        done += n
        cl.enqueue_copy(q, nh, nh_buf); q.finish()
        k = min(int(nh[0]), maxhits)
        if k:
            raw = np.empty(k * 8, dtype=np.uint8)
            cl.enqueue_copy(q, raw, hits_buf); q.finish()
            found = [bytes(raw[i * 8:(i + 1) * 8]).rstrip(b'\0').decode() for i in range(k)]
        if not quiet:
            el = time.time() - t0
            print(f'\r  gpu: {done:,} seeds  {done / max(el, 1e-9):,.0f}/s  {int(nh[0])} hits', end='', file=sys.stderr, flush=True)
    if not quiet:
        print(file=sys.stderr)
    return found, done, time.time() - t0, dev.name

def selftest():
    from engine import load_data
    from bridge import build_cfg, parse_crit, py_check
    import searcher
    D = load_data()
    cases = [({}, ['legend:any:1-2']), ({}, ['shop:any:1-1:edition=foil']),
             ({'skips': {'1s'}, 'buy_vouchers': ['v_overstock_norm']}, ['joker:any:1-2:edition=holo', 'pack:any:1-2:seal=red'])]
    ok_all = True
    for opts, specs in cases:
        crits = [parse_crit(D, s) for s in specs]
        antes = max(c.hi for c in crits)
        cfg = build_cfg(D, opts)
        N = 200_000
        found, done, dt, name = search_range(cfg, crits, antes, 0, N, maxhits=200_000, quiet=True, lens=(1, 8))
        exe = searcher.build_cpu()
        if exe:
            ref = set(searcher.run_cpu_raw(exe, cfg, crits, antes, 0, N, None, 10 ** 7, 0, (1, 8)))
            src = 'C core'
        else:
            N2 = 4000
            ref = {searcher.idx2seed(i, 1, 8) for i in range(N2) if py_check(searcher.idx2seed(i, 1, 8), D, opts, crits)}
            found = [s for s in found if searcher.seed2idx(s, 1, 8) < N2]
            src = f'Python engine (first {N2} seeds)'
        same = set(found) == ref
        ok_all &= same
        print(f"{name}: {specs}: GPU {len(set(found))} hits / {src} {len(ref)} hits -> {'OK' if same else 'DIFFERENT'}  ({done / dt:,.0f} seeds/s)")
    print('SELFTEST PASSED - the GPU kernel agrees with the reference.' if ok_all else
          'SELFTEST FAILED - do not use --engine gpu; use --engine cpu and please report this output.')
    return 0 if ok_all else 1

if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    if '--bench' in sys.argv:
        from engine import load_data
        from bridge import parse_crit, build_cfg
        D = load_data()
        for spec in ('legend:any:1-1', 'shop:Blueprint:1-2', 'joker:Blueprint:1-2'):
            c = [parse_crit(D, spec)]
            f, done, dt, name = search_range(build_cfg(D, {}), c, c[0].hi, 10 ** 9, 4_000_000, maxhits=10 ** 6, quiet=True)
            print(f'{name}: {spec}: {done / dt:,.0f} seeds/s')
        sys.exit(0)
    print(__doc__)
