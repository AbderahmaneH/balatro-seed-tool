/* CPU driver for core.h.  Normally called by find_seeds.py, which turns names into the numeric arguments.
   gcc -O2 -ffp-contract=off -fopenmp search.c -o bsearch -lm
   ./bsearch --cfg 0,0,... --crit loc,id,lo,hi,ed,seal,count,shopmask,rerolls,card,enh [--crit ...] --antes N --start S --count C
   ./bsearch --cfg ... --trace SEED --antes N          (prints every emitted event; used by difftest.py)          */
#define WITH_NAMES
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _OPENMP
#include <omp.h>
#endif
#include "core.h"

static const char CH[] = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ";
/* seed space = all seeds with length lmin..lmax, shortest first (shortlex). returns the length */
static u64 POW34[9];
static int idx2seed(u64 n, int lmin, int lmax, u8 *s) {
  int L, i;
  for (L = lmin; L < lmax && n >= POW34[L]; L++) n -= POW34[L];
  for (i = L - 1; i >= 0; i--) { s[i] = (u8)CH[n % 34]; n /= 34; }
  return L;
}

static int parse_ints(const char *s, int *out, int max) {
  int n = 0; char *e;
  while (*s && n < max) { out[n++] = (int)strtol(s, &e, 10); if (e == s) break; s = e; if (*s == ',') s++; }
  return n;
}

int main(int argc, char **argv) {
  static int cfg[CFG_SIZE];
  static Crit CR[MAXCR]; int ncr = 0;
  int i, antes = 3, maxhits = 50, rnd = 0, threads = 0, lmin = 8, lmax = 8;
  u64 space = 0;
  u64 start = 0, count = 1000000, rstate = 88172645463325252ULL;
  const char *trace = NULL;
  memset(cfg, 0, sizeof cfg);
  cfg[CFG_TAKE_SOULS] = 1; cfg[CFG_MOST_PLANET] = -1; cfg[CFG_START_HELD] = 1;
  for (i = 1; i < argc; i++) {
    const char *a = argv[i];
    if (!strcmp(a, "--cfg")) { parse_ints(argv[++i], cfg, CFG_SIZE); }
    else if (!strcmp(a, "--crit")) {
      int v[12]; int n = parse_ints(argv[++i], v, 12);
      if (n < 11 || ncr >= MAXCR) { fprintf(stderr, "bad --crit\n"); return 2; }
      if (n == 11) v[11] = 0;
      CR[ncr].loc = v[0]; CR[ncr].id = v[1]; CR[ncr].lo = v[2]; CR[ncr].hi = v[3]; CR[ncr].edition = v[4]; CR[ncr].seal = v[5];
      CR[ncr].count = v[6]; CR[ncr].shopmask = v[7]; CR[ncr].rerolls = v[8]; CR[ncr].card = v[9]; CR[ncr].enh = v[10]; CR[ncr].rarity = v[11]; ncr++;
    }
    else if (!strcmp(a, "--antes")) antes = atoi(argv[++i]);
    else if (!strcmp(a, "--trace")) trace = argv[++i];
    else if (!strcmp(a, "--start")) start = strtoull(argv[++i], 0, 10);
    else if (!strcmp(a, "--count")) count = strtoull(argv[++i], 0, 10);
    else if (!strcmp(a, "--random")) { rnd = 1; rstate ^= strtoull(argv[++i], 0, 10) * 0x9E3779B97F4A7C15ULL; }
    else if (!strcmp(a, "--hits")) maxhits = atoi(argv[++i]);
    else if (!strcmp(a, "--lens")) { if (sscanf(argv[++i], "%d,%d", &lmin, &lmax) != 2) { fprintf(stderr, "bad --lens\n"); return 2; } }
    else if (!strcmp(a, "--threads")) threads = atoi(argv[++i]);
    else { fprintf(stderr, "unknown arg %s\n", a); return 2; }
  }
  if (antes > MAXANTE) antes = MAXANTE;
  if (lmin < 1) lmin = 1; if (lmax > 8) lmax = 8; if (lmin > lmax) lmin = lmax;
  POW34[0] = 1; for (i = 1; i <= 8; i++) POW34[i] = POW34[i - 1] * 34;
  for (i = lmin; i <= lmax; i++) space += POW34[i];
  if (trace) {
    Run R; int r;
    run_init(&R, (const u8 *)trace, (int)strlen(trace), cfg, CR, ncr);
    R.trace = 1; R.need_mods = 1; R.soul_only = 0; R.no_packs = 0; R.no_ed = 0;
    r = simulate(&R, antes);
    printf("R %d\n", r);
    return 0;
  }
#ifdef _OPENMP
  if (threads > 0) omp_set_num_threads(threads);
#endif
  {
    int hits = 0; long long k;
    #pragma omp parallel for schedule(dynamic, 2048)
    for (k = 0; k < (long long)count; k++) {
      u8 s[9]; Run R; u64 idx; int r, L;
      if (hits >= maxhits) continue;
      if (rnd) { u64 x = rstate + (u64)k * 0x9E3779B97F4A7C15ULL; x ^= x >> 30; x *= 0xBF58476D1CE4E5B9ULL; x ^= x >> 27; x *= 0x94D049BB133111EBULL; x ^= x >> 31; idx = x % space; }
      else idx = start + (u64)k;
      if (idx >= space) continue;
      L = idx2seed(idx, lmin, lmax, s); s[L] = 0;
      run_init(&R, s, L, cfg, CR, ncr);
      r = simulate(&R, antes);
      if (r) {
        #pragma omp critical
        { if (hits < maxhits) { printf("%s %d\n", (char *)s, r); fflush(stdout); hits++; } }
      }
    }
  }
  return 0;
}
