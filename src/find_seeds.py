#!/usr/bin/env python3
"""
Balatro seed finder - give criteria, get seeds.  Same rules and options as analyze.py.

  python find_seeds.py --want legend:any:1:count=3                       # 3 legendaries in ante 1
  python find_seeds.py --want legend:Perkeo:1-2 --want shop:Blueprint:1-3
  python find_seeds.py --want joker:any:1-2:edition=negative --want voucher:Telescope:1
  python find_seeds.py --want shop:Blueprint:1:rerolls=10                # reachable with <=10 rerolls
  python find_seeds.py --want joker:rare:1-2:count=2                     # 2 Rare jokers by ante 2
  python find_seeds.py --want legend:any:1:count=2 --deck Magic --buy-voucher "Omen Globe" --random 7
  python find_seeds.py --want legend:any:1 --length 1-4          # every seed of 1-4 characters (1.4M seeds)

Seeds may be 1 to 8 characters. --length chooses which lengths are searched (default 1-8: shortest first).

CRITERION =  LOCATION:ITEM[:ANTES][:option=value ...]
  LOCATION  shop | pack | legend | joker | voucher | tag | boss | packtype | card
  ITEM      in-game name or key, "any", or a rarity: common | uncommon | rare | legendary
            (card: a playing card such as "Ace of Spades")
  ANTES     1  or  1-3                               (in-game antes; default 1; search supports up to 8)
  options   count=N  rarity=common|uncommon|rare|legendary  edition=foil|holo|polychrome|negative
            seal=red|blue|gold|purple  enh=<Enhancement>
            shop=s|b|x|tag (which shop: after Small/Big/Boss blind, or tag packs; combine with +)  rerolls=N
Full documentation: GUIDE.md / GUIDE.pdf
"""
import argparse, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from engine import load_data, valid_seed
from bridge import parse_crit
from analyze import add_common_args, build_opts
from searcher import SearchJob, seed2idx, parse_lengths, space_size

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--want', action='append', required=True, help='criterion (repeatable, all must match)')
    ap.add_argument('--engine', choices=['auto', 'cpu', 'gpu', 'py'], default='auto')
    ap.add_argument('--length', default='1-8', help='seed lengths to search: 8, 1-8, 3-5 ... (default 1-8, shortest first)')
    ap.add_argument('--count', type=int, default=20_000_000, help='number of seeds to scan (default 20M)')
    ap.add_argument('--start', type=int, default=0, help='first index in the seed space (0 = first seed)')
    ap.add_argument('--from', dest='from_seed', help='start the scan at this seed')
    ap.add_argument('--random', type=int, default=None, help='scan random seeds instead (value = sampling seed)')
    ap.add_argument('--hits', type=int, default=10, help='stop after this many hits')
    ap.add_argument('--threads', type=int, default=0)
    ap.add_argument('--show', action='store_true', help='print the full analysis of every hit')
    ap.add_argument('--out', help='save results (.md, .csv or .txt)')
    add_common_args(ap)
    a = ap.parse_args()
    D = load_data()
    try:
        opts = build_opts(a, D)
        crits = [parse_crit(D, w) for w in a.want]
        lens = parse_lengths(a.length)
        start = a.start
        if a.from_seed:
            if not valid_seed(a.from_seed.upper()):
                raise ValueError('--from must be a valid seed')
            start = seed2idx(a.from_seed, *lens)
    except ValueError as e:
        sys.exit(str(e))
    if len(crits) > 16:
        sys.exit('at most 16 criteria')
    job = SearchJob(D, opts, crits, a.engine, a.count, start, a.random, lens, a.hits, a.threads)
    print(f"criteria: {' AND '.join(c.spec for c in crits)}   seeds of length {lens[0]}-{lens[1]} "
          f"({space_size(*lens):,} in total)", file=sys.stderr)
    th = job.start_thread()
    shown = 0
    try:
        while th.is_alive():
            th.join(0.5)
            st = job.status()
            print(f"\r  [{st['engine']}] {st['scanned']:,} seeds  {st['rate']:,.0f}/s  {len(st['results'])} hits   ",
                  end='', file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        job.stop(); th.join()
    st = job.status()
    print(file=sys.stderr)
    if st['state'] == 'error':
        sys.exit('error: ' + st['message'])
    res = st['results']
    print(f"\n{len(res)} seed(s) found - {st['scanned']:,} seeds scanned in {st['elapsed']:.1f}s ({st['rate']:,.0f}/s)")
    for r in res:
        print(f"\n  {r['seed']}")
        for c, d in zip(crits, r['desc']):
            print(f"     {c.spec:<34} {d}")
    if not res:
        print("No match - scan more seeds (--count), loosen the criteria, or use --random to sample elsewhere.")
    if a.out:
        ext = a.out.rsplit('.', 1)[-1].lower()
        with open(a.out, 'w', encoding='utf-8') as f:
            if ext == 'csv':
                f.write('seed,' + ','.join('"' + c.spec + '"' for c in crits) + '\n')
                for r in res:
                    f.write(r['seed'] + ',' + ','.join('"' + d.replace('"', "'") + '"' for d in r['desc']) + '\n')
            elif ext == 'md':
                f.write('# Seeds found\n\nCriteria: ' + ' AND '.join(f'`{c.spec}`' for c in crits) + '\n\n')
                f.write('| Seed | ' + ' | '.join(c.spec for c in crits) + ' |\n|' + '---|' * (len(crits) + 1) + '\n')
                for r in res:
                    f.write(f"| **{r['seed']}** | " + ' | '.join(r['desc']) + ' |\n')
            else:
                for r in res:
                    f.write(r['seed'] + '\t' + ' | '.join(r['desc']) + '\n')
        print(f"\nsaved {a.out}")
    if a.show:
        import analyze
        from engine import Run
        for r in res:
            run = Run(r['seed'], D, **opts)
            T = run.simulate(job.antes)
            print('\n' + analyze.render(D, a, run, T, 'text'))

if __name__ == '__main__':
    main()
