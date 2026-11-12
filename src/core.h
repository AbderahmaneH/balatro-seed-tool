/* Balatro seed core v2 - portable C / OpenCL C.  Mirrors engine.py step by step (same RNG call order).
   C:      gcc -O2 -ffp-contract=off ...         OpenCL: #define BALATRO_OPENCL before including (gpu_search.py does) */
#ifdef BALATRO_OPENCL
  #pragma OPENCL EXTENSION cl_khr_fp64 : enable
  #pragma OPENCL FP_CONTRACT OFF
  #define CONSTANT __constant
  #define CPARAM __constant
  typedef ulong u64; typedef uint u32; typedef uchar u8;
  #define U2D(x) as_double(x)
  #define D2U(x) as_ulong(x)
  #define INLINE inline
#else
  #include <stdint.h>
  #include <math.h>
  #include <string.h>
  #include <stdio.h>
  #define CONSTANT static const
  #define CPARAM const
  typedef uint64_t u64; typedef uint32_t u32; typedef uint8_t u8;
  static inline double U2D(u64 x){ union{u64 u;double d;} v; v.u=x; return v.d; }
  static inline u64 D2U(double x){ union{u64 u;double d;} v; v.d=x; return v.u; }
  #define INLINE static inline
#endif
#include "core_data.h"

#define PI_D 3.14159265358979323846
#define E_D  2.7182818284590452354
#define NS 200
#define MAXJ 16
#define MAXTAGS 24
#define MAXSHOP 8
#define MAXCR 16
#define MAXANTE 39
#define ABASE 64          /* ante base for stream ids; supports antes 1..63 */

/* config array layout (shared with host / GPU) */
#define CFG_MODE 0
#define CFG_PLAYED 1
#define CFG_DECK 2            /* 0 other 1 ghost 2 magic 3 nebula 4 zodiac 5 black 6 painted */
#define CFG_TAKE_SOULS 3
#define CFG_MOST_PLANET 4     /* planet item id forced by Telescope, -1 unknown */
#define CFG_START_HELD 5
#define CFG_SKIPS 6           /* bit (g-1)*3+k  for k: 0 small 1 big */
#define CFG_SKIP_TAGPACK 7    /* bits: 0 charm 1 buffoon 2 meteor 3 ethereal 4 standard */
#define CFG_SKIP_PACK_LO 8    /* bit shopidx*2+j (shopidx 0..15) */
#define CFG_SKIP_PACK_HI 9    /* shopidx 16..23 */
#define CFG_RER 10            /* 24 entries: rerolls per shop index */
#define CFG_LISTS 34          /* n_take ids.., n_buy ids.., n_own ids.., n_locked ids.. */
#define CFG_SIZE 256

/* emission locations */
#define E_SHOP 0
#define E_PACK 1
#define E_VOUCHER 2
#define E_TAG 3
#define E_BOSS 4
#define E_LEGEND 5
#define E_PACKTYPE 6
#define E_TOPUP 7
/* criteria locations */
#define C_SHOP 0
#define C_PACK 1
#define C_VOUCHER 2
#define C_TAG 3
#define C_BOSS 4
#define C_LEGEND 5
#define C_PACKTYPE 6
#define C_JOKER 7
#define C_CARD 8

typedef struct { int loc, id, lo, hi, edition, seal, count, shopmask, rerolls, card, enh, rarity; } Crit;
typedef struct { u64 u[4]; } Rng;
typedef struct { int id, ed, seal, card, leg, leged; } Card;

typedef struct {
  Rng rng; double hs; u8 seed[8]; int slen; u32 sdv; double sd[32];
  int n; int sid[NS]; double st[NS]; int overflow; short hix[512];
  int ante, g, kind, rr;
  u32 used[N_WORDS], vused[N_WORDS], take[N_WORDS], buy[N_WORDS], locked[N_WORDS];
  int nj, jk[MAXJ], jed[MAXJ];
  int ntags, tags[MAXTAGS];
  int boss_used[N_BLINDS];
  double r_joker, r_tarot, r_planet, r_pc, r_spec, ed_rate;
  int joker_max, joker_slots, first_buf, cur_voucher, cur_boss;
  int nsv, sv[6];
  int nsc; Card sc[MAXSHOP]; int sc_taken[MAXSHOP];
  int mode, played, take_souls, most_planet, deck, skips, skip_tagpack, ntake; int rer[24]; u32 skip_lo, skip_hi;
  CPARAM Crit *cr; int ncr; int cnt[MAXCR]; int maxrr; int trace; int soul_only; int need_mods; int no_packs, no_ed;
} Run;

#define BGET(a,i) (((a)[(i)>>5] >> ((i)&31)) & 1u)
#define BSET(a,i) ((a)[(i)>>5] |= (1u << ((i)&31)))
#define BCLR(a,i) ((a)[(i)>>5] &= ~(1u << ((i)&31)))

/* ---------------- LuaJIT PRNG ---------------- */
INLINE void rng_step(Rng *r, u64 *out) {
  u64 z, o = 0;
  z = r->u[0]; z = (((z<<31)^z) >> (63-18)) ^ ((z & (~(u64)0 << (64-63))) << 18); o ^= z; r->u[0] = z;
  z = r->u[1]; z = (((z<<19)^z) >> (58-28)) ^ ((z & (~(u64)0 << (64-58))) << 28); o ^= z; r->u[1] = z;
  z = r->u[2]; z = (((z<<24)^z) >> (55-7))  ^ ((z & (~(u64)0 << (64-55))) << 7);  o ^= z; r->u[2] = z;
  z = r->u[3]; z = (((z<<21)^z) >> (47-8))  ^ ((z & (~(u64)0 << (64-47))) << 8);  o ^= z; r->u[3] = z;
  *out = o;
}
INLINE void rng_seed(Rng *r, double d) {
  u32 rr = 0x11090601u; int i; u64 tmp;
  for (i = 0; i < 4; i++) {
    u64 m = (u64)1 << (rr & 255); u64 uu;
    rr >>= 8;
    d = d * PI_D + E_D;
    uu = D2U(d);
    if (uu < m) uu += m;
    r->u[i] = uu;
  }
  for (i = 0; i < 10; i++) rng_step(r, &tmp);
}
INLINE double rng_double(Rng *r) {
  u64 o; rng_step(r, &o);
  return U2D((o & 0x000fffffffffffffUL) | 0x3ff0000000000000UL) - 1.0;
}
INLINE int rng_pick(Rng *r, double seedv, int n) { rng_seed(r, seedv); return (int)floor(rng_double(r) * (double)n) + 1; }
INLINE double rng_rand(Rng *r, double seedv) { rng_seed(r, seedv); return rng_double(r); }

/* ---------------- pseudohash / pseudoseed ---------------- */
INLINE double round13(double v) {      /* tonumber(string.format("%.13f", v)) - exact via fma */
  double hi = v * 1e13;
  double lo = fma(v, 1e13, -hi);
  double f = floor(hi);
  double frac = (hi - f) + lo;
  double k = f + (frac > 0.5 ? 1.0 : 0.0);
  return k / 1e13;
}
INLINE double step13(double s) { double v = 2.134453429141 + s * 1.72431234; v = v - floor(v); return round13(v); }

INLINE double phash_key(Run *R, const u8 *b, int L) {   /* pseudohash(key .. seed); seed part cached per key length */
  double num; int i;
  if (R->sdv & ((u32)1 << L)) num = R->sd[L];
  else {
    num = 1.0;
    for (i = L + R->slen; i >= L + 1; i--) {
      num = ((1.1239285023 / num) * (double)R->seed[i - L - 1] * PI_D + PI_D * (double)i);
      num = num - floor(num);
    }
    R->sd[L] = num; R->sdv |= ((u32)1 << L);
  }
  for (i = L; i >= 1; i--) {
    num = ((1.1239285023 / num) * (double)b[i-1] * PI_D + PI_D * (double)i);
    num = num - floor(num);
  }
  return num;
}

INLINE double pseudoseed(Run *R, int kind, int ante, int it) {
  int a = KEY_HAS_ANTE[kind] ? ante : 0;
  int sid = (kind * ABASE + a) * 256 + it;
  int found = -1; double st;
  u32 h = ((u32)sid * 2654435761u) >> 23;
  while (R->hix[h]) { if (R->sid[R->hix[h] - 1] == sid) { found = R->hix[h] - 1; break; } h = (h + 1) & 511; }
  if (found < 0) {
    u8 buf[48]; int L = 0, j;
    for (j = 0; j < KEY_PRE_LEN[kind]; j++) buf[L++] = KEY_BLOB[KEY_PRE_OFF[kind] + j];
    if (KEY_HAS_ANTE[kind]) { if (ante >= 10) buf[L++] = (u8)('0' + ante / 10); buf[L++] = (u8)('0' + ante % 10); }
    for (j = 0; j < KEY_POST_LEN[kind]; j++) buf[L++] = KEY_BLOB[KEY_POST_OFF[kind] + j];
    if (it > 0) {
      buf[L++]='_';buf[L++]='r';buf[L++]='e';buf[L++]='s';buf[L++]='a';buf[L++]='m';buf[L++]='p';buf[L++]='l';buf[L++]='e';
      if (it >= 100) buf[L++] = (u8)('0' + it / 100);
      if (it >= 10) buf[L++] = (u8)('0' + (it / 10) % 10);
      buf[L++] = (u8)('0' + it % 10);
    }
    st = phash_key(R, buf, L);
    if (R->n >= NS) { R->overflow = 1; R->n = NS - 1; }
    found = R->n++; R->sid[found] = sid; R->hix[h] = (short)(found + 1);
  } else st = R->st[found];
  st = step13(st);
  R->st[found] = st;
  return (st + R->hs) / 2.0;
}
INLINE double prand(Run *R, int kind, int ante) { return rng_rand(&R->rng, pseudoseed(R, kind, ante, 0)); }

/* ---------------- existence tracking (G.GAME.used_jokers) ---------------- */
INLINE int showman(Run *R) { int i; for (i = 0; i < R->nj; i++) if (R->jk[i] == ID_J_RING_MASTER) return 1; return 0; }
INLINE int owned(Run *R, int id) { int i; for (i = 0; i < R->nj; i++) if (R->jk[i] == id) return 1; return 0; }
INLINE void created(Run *R, int id) { if (id >= 0) BSET(R->used, id); }
INLINE void removed(Run *R, int id) { if (id >= 0 && !owned(R, id)) BCLR(R->used, id); }
INLINE int free_slots(Run *R) { int i, neg = 0; for (i = 0; i < R->nj; i++) if (R->jed[i] == 4) neg++; return R->joker_slots + neg - R->nj; }
INLINE void gain_joker(Run *R, int id, int ed) { if (R->nj < MAXJ) { R->jk[R->nj] = id; R->jed[R->nj] = ed; R->nj++; } else R->overflow = 1; BSET(R->used, id); }

/* dynamic pool checks; cls 0 = jokers/consumables, 1 = vouchers, 2 = no dynamic check (tags, enhanced, cards) */
INLINE int pool_ok(Run *R, int c, int cls, int sm) {
  int i;
  if (c < 0) return 0;
  if (cls == 2) return 1;
  if (BGET(R->used, c) && !sm) return 0;
  if (BGET(R->locked, c)) return 0;
  if (cls == 1) {
    if (BGET(R->vused, c)) return 0;
    if (VREQ[c] >= 0 && !BGET(R->vused, VREQ[c])) return 0;
    for (i = 0; i < R->nsv; i++) if (R->sv[i] == c) return 0;
  }
  return 1;
}
INLINE int draw_pool(Run *R, int pid, int kind, int ante, int cls, int fallback) {
  int len = POOL_LEN[pid], off = POOL_OFF[pid], sm = showman(R), i, any = 0;
  int idx = rng_pick(&R->rng, pseudoseed(R, kind, ante, 0), len);
  int c = POOL_FLAT[off + idx - 1], it = 1;
  if (pool_ok(R, c, cls, sm)) return c;
  for (i = 0; i < len; i++) if (pool_ok(R, POOL_FLAT[off + i], cls, sm)) { any = 1; break; }
  if (!any) return fallback;            /* get_current_pool's empty-pool fallback */
  while (1) {
    it++;
    if (it > 250) { R->overflow = 1; return fallback; }
    idx = rng_pick(&R->rng, pseudoseed(R, kind, ante, it), len);
    c = POOL_FLAT[off + idx - 1];
    if (pool_ok(R, c, cls, sm)) return c;
  }
}
INLINE int pid_joker(int rar, int mode) { return mode * 7 + (rar - 1); }

/* 0 none 1 foil 2 holo 3 polychrome 4 negative */
INLINE int poll_edition(Run *R, int kind, int ante, double mod, int no_neg) {
  double p = prand(R, kind, ante);
  if (p > 1.0 - 0.003 * mod && !no_neg) return 4;
  if (p > 1.0 - 0.006 * R->ed_rate * mod) return 3;
  if (p > 1.0 - 0.02 * R->ed_rate * mod) return 2;
  if (p > 1.0 - 0.04 * R->ed_rate * mod) return 1;
  return 0;
}

/* ---------------- emission + criteria ---------------- */
INLINE int crit_match(CPARAM Crit *c, int loc, int id, int ed, int seal, int card, int g, int kind, int rr) {
  if (g < c->lo || g > c->hi) return 0;
  if (rr > c->rerolls) return 0;
  if (c->shopmask && !(c->shopmask & (1 << kind))) return 0;
  if (c->edition && c->edition != ed) return 0;
  if (c->seal && c->seal != seal) return 0;
  if (c->rarity && (id < 0 || ITEM_RARITY[id] != c->rarity)) return 0;
  switch (c->loc) {
    case C_SHOP:     return loc == E_SHOP && (c->id < 0 || c->id == id);
    case C_PACK:     return loc == E_PACK && (c->id < 0 || c->id == id);
    case C_VOUCHER:  return loc == E_VOUCHER && (c->id < 0 || c->id == id);
    case C_TAG:      return loc == E_TAG && (c->id < 0 || c->id == id);
    case C_BOSS:     return loc == E_BOSS && (c->id < 0 || c->id == id);
    case C_LEGEND:   return loc == E_LEGEND && (c->id < 0 || c->id == id);
    case C_PACKTYPE: return loc == E_PACKTYPE && (c->id < 0 || c->id == ITEM_GROUP[id]);
    case C_JOKER:    return (loc == E_SHOP || loc == E_PACK || loc == E_LEGEND || loc == E_TOPUP) && id >= 0 && ITEM_KIND[id] == 1 && (c->id < 0 || c->id == id);
    case C_CARD:     return (loc == E_SHOP || loc == E_PACK) && card >= 0 && (c->card < 0 || c->card == card) && (c->enh < 0 || c->enh == id);
  }
  return 0;
}
INLINE void emit(Run *R, int loc, int id, int ed, int seal, int card) {
  int i;
#ifndef BALATRO_OPENCL
  if (R->trace) printf("E %d %d %d %d %d %d %d %d\n", loc, R->g, R->kind, R->rr, id, ed, seal, card);
#endif
  for (i = 0; i < R->ncr; i++) if (crit_match(&R->cr[i], loc, id, ed, seal, card, R->g, R->kind, R->rr)) R->cnt[i]++;
}
INLINE void emit_card(Run *R, int loc, Card *c) {
  emit(R, loc, c->id, c->ed, c->seal, c->card);
  if (c->leg >= 0) emit(R, E_LEGEND, c->leg, c->leged, 0, -1);
}

/* ---------------- card creation ---------------- */
INLINE void card0(Card *c) { c->id = -1; c->ed = 0; c->seal = 0; c->card = -1; c->leg = -1; c->leged = 0; }

/* src: 0 shop 'sho', 1 buffoon pack 'buf', 2 uncommon tag 'uta', 3 rare tag 'rta', 4 top-up 'top', 5 soul 'sou' */
INLINE void make_joker(Run *R, int src, Card *c) {
  int rr, kind, ek;
  card0(c);
  if (src == 5) {
    c->id = draw_pool(R, pid_joker(4, R->mode), K_LEGEND, R->ante, 0, ID_J_JOKER);
    created(R, c->id);
    c->ed = R->no_ed ? 0 : poll_edition(R, K_EDI_SOU, R->ante, 1.0, 0);
    return;
  }
  if (src == 2) rr = 2; else if (src == 3) rr = 3; else if (src == 4) rr = 1;
  else {
    double r = prand(R, src == 0 ? K_RARITY_SHO : K_RARITY_BUF, R->ante);
    rr = r > 0.95 ? 3 : (r > 0.7 ? 2 : 1);
  }
  if (src == 0) { kind = K_JK1_SHO + rr - 1; ek = K_EDI_SHO; }
  else if (src == 1) { kind = K_JK1_BUF + rr - 1; ek = K_EDI_BUF; }
  else if (src == 2) { kind = K_JK2_UTA; ek = K_EDI_UTA; }
  else if (src == 3) { kind = K_JK3_RTA; ek = K_EDI_RTA; }
  else { kind = K_JK1_TOP; ek = K_EDI_TOP; }
  c->id = draw_pool(R, pid_joker(rr, R->mode), kind, R->ante, 0, ID_J_JOKER);
  created(R, c->id);
  c->ed = R->no_ed ? 0 : poll_edition(R, ek, R->ante, 1.0, 0);
}

/* typ 2 tarot 3 planet 4 spectral; poolkind = stream for the pool draw; soulable: pack cards */
INLINE void make_consumable(Run *R, int typ, int poolkind, int soulable, int forced, Card *c) {
  int sm = showman(R);
  card0(c);
  if (forced < 0 && soulable) {
    if ((typ == 2 || typ == 4) && !(BGET(R->used, ID_C_SOUL) && !sm))
      if (prand(R, typ == 2 ? K_SOUL_TAROT : K_SOUL_SPECTRAL, R->ante) > 0.997) forced = ID_C_SOUL;
    if ((typ == 3 || typ == 4) && !(BGET(R->used, ID_C_BLACK_HOLE) && !sm))
      if (prand(R, typ == 3 ? K_SOUL_PLANET : K_SOUL_SPECTRAL, R->ante) > 0.997) forced = ID_C_BLACK_HOLE;
  }
  if (forced >= 0) c->id = forced;
  else if (R->soul_only) c->id = -1;
  else if (typ == 2) c->id = draw_pool(R, PID_TAROT, poolkind, R->ante, 0, ID_C_STRENGTH);
  else if (typ == 3) c->id = draw_pool(R, PID_PLANET_P0 + R->played, poolkind, R->ante, 0, ID_C_PLUTO);
  else c->id = draw_pool(R, PID_SPECTRAL, poolkind, R->ante, 0, ID_C_INCANTATION);
  created(R, c->id);
}

/* playing card: enh = 0 Base, 1 Enhanced.  src 0 shop, 1 standard pack */
INLINE void make_playing(Run *R, int enh, int src, Card *c) {
  card0(c);
  c->id = enh ? draw_pool(R, PID_ENHANCED, src ? K_ENH : K_ENH_SHO, R->ante, 2, -1) : ID_C_BASE;
  c->card = rng_pick(&R->rng, pseudoseed(R, src ? K_FRONT : K_FRONT_SHO, R->ante, 0), N_CARDS) - 1;
  created(R, c->id);
}

/* ---------------- tags ---------------- */
INLINE void del_tag(Run *R, int i) { int j; for (j = i; j < R->ntags - 1; j++) R->tags[j] = R->tags[j + 1]; R->ntags--; }
INLINE void push_tag(Run *R, int t) { if (R->ntags < MAXTAGS) R->tags[R->ntags++] = t; else R->overflow = 1; }

INLINE void modify_tags(Run *R, Card *c) {
  int i, t;
  if (c->id < 0 || ITEM_KIND[c->id] != 1 || c->ed) return;
  for (i = 0; i < R->ntags; i++) {
    t = R->tags[i];
    if (TAGTYPE[t] == 2) {
      c->ed = t == ID_TAG_FOIL ? 1 : t == ID_TAG_HOLO ? 2 : t == ID_TAG_POLYCHROME ? 3 : 4;
      del_tag(R, i);
      return;
    }
  }
}

/* ---------------- shop slot ---------------- */
INLINE void shop_slot(Run *R, Card *c) {
  int i, t, illusion, pc_enh = 0;
  double total, polled, check;
  for (i = 0; i < R->ntags; i++) {
    t = R->tags[i];
    if (TAGTYPE[t] == 1) {
      make_joker(R, t == ID_TAG_UNCOMMON ? 2 : 3, c);
      del_tag(R, i);
      modify_tags(R, c);
      return;
    }
  }
  total = R->r_joker + R->r_tarot + R->r_planet + R->r_pc + R->r_spec;
  polled = prand(R, K_CDT, R->ante) * total;
  illusion = BGET(R->vused, ID_V_ILLUSION);
  if (illusion && prand(R, K_ILLUSION, 0) > 0.6) pc_enh = 1;
  card0(c);
  check = 0;
  if (polled > check && polled <= check + R->r_joker) { make_joker(R, 0, c); modify_tags(R, c); return; }
  check += R->r_joker;
  if (polled > check && polled <= check + R->r_tarot) { make_consumable(R, 2, K_TAROT_SHO, 0, -1, c); return; }
  check += R->r_tarot;
  if (polled > check && polled <= check + R->r_planet) { make_consumable(R, 3, K_PLANET_SHO, 0, -1, c); return; }
  check += R->r_planet;
  if (polled > check && polled <= check + R->r_pc) {
    make_playing(R, pc_enh, 0, c);
    if (illusion && prand(R, K_ILLUSION, 0) > 0.8) {
      double ep = prand(R, K_ILLUSION, 0);
      c->ed = ep > 1 - 0.15 ? 3 : (ep > 0.5 ? 2 : 1);
    }
    return;
  }
  check += R->r_pc;
  if (polled > check && polled <= check + R->r_spec) { make_consumable(R, 4, K_SPECTRAL_SHO, 0, -1, c); return; }
}

/* ---------------- vouchers / boss / packs ---------------- */
INLINE int next_voucher(Run *R, int from_tag) {
  return draw_pool(R, R->mode * 7 + 4, from_tag ? K_VOUCHER_TAG : K_VOUCHER, R->ante, 1, ID_V_BLANK);
}
INLINE int next_tag(Run *R) {
  return draw_pool(R, R->mode * 7 + 5 + (R->ante >= 2 ? 1 : 0), K_TAG, R->ante, 2, ID_TAG_HANDY);
}
INLINE void redeem(Run *R, int v, int in_shop);

INLINE int get_pack(Run *R) {
  double cume = 0, it = 0, poll; int i;
  if (!R->first_buf) { R->first_buf = 1; return BOOSTER_BUFFOON_NORMAL_1; }
  for (i = 0; i < N_BOOSTERS; i++) cume = cume + BOOST_W[i];
  poll = prand(R, K_SHOP_PACK, R->ante) * cume;
  for (i = 0; i < N_BOOSTERS; i++) {
    it = it + BOOST_W[i];
    if (it >= poll && it - BOOST_W[i] <= poll) return i;
  }
  return 0;
}

INLINE int new_boss(Run *R) {
  int i, minuse = 100, cnt = 0, elig[N_BLINDS], k, pick, a = R->ante;
  int a1 = a < 1 ? 1 : a;
  for (i = 0; i < N_BLINDS; i++) {
    elig[i] = 0;
    if (!BLIND_BOSS[i]) continue;
    if (!BLIND_SHOW[i] && BLIND_MIN[i] <= a1 && ((a1 % 8) != 0 || a < 2)) elig[i] = 1;
    else if (BLIND_SHOW[i] && (a % 8) == 0 && a >= 2) elig[i] = 1;
  }
  for (i = 0; i < N_BLINDS; i++) if (elig[i] && R->boss_used[i] <= minuse) minuse = R->boss_used[i];
  for (i = 0; i < N_BLINDS; i++) if (elig[i] && R->boss_used[i] > minuse) elig[i] = 0;
  for (i = 0; i < N_BLINDS; i++) if (elig[i]) cnt++;
  pick = rng_pick(&R->rng, pseudoseed(R, K_BOSS, 0, 0), cnt);
  for (i = 0, k = 0; i < N_BLINDS; i++) if (elig[i]) { k++; if (k == pick) break; }
  R->boss_used[i]++;
  return BLIND_ID[i];
}

INLINE void use_soul(Run *R, Card *soul) {
  Card L;
  make_joker(R, 5, &L);
  gain_joker(R, L.id, L.ed);
  soul->leg = L.id; soul->leged = L.ed;
}

/* open + close one pack, emit its cards */
INLINE void open_pack(Run *R, int b) {
  Card cs[5]; int taken[5];
  int pk = BOOST_KIND[b], n = BOOST_N[b], picks = BOOST_CHOOSE[b], i;
  if (R->no_packs) return;
  for (i = 0; i < n; i++) {
    taken[i] = 0;
    if (pk == 0) {
      if (BGET(R->vused, ID_V_OMEN_GLOBE) && rng_rand(&R->rng, pseudoseed(R, K_OMEN, 0, 0)) > 0.8)
        make_consumable(R, 4, K_SPECTRAL_AR2, 1, -1, &cs[i]);
      else make_consumable(R, 2, K_TAROT, 1, -1, &cs[i]);
    } else if (pk == 1) {
      int forced = -1;
      if (BGET(R->vused, ID_V_TELESCOPE) && i == 0 && R->most_planet >= 0) forced = R->most_planet;
      make_consumable(R, 3, K_PLANET, 1, forced, &cs[i]);
    } else if (pk == 5) {
      make_consumable(R, 4, K_SPECTRAL, 1, -1, &cs[i]);
    } else if (pk == 2) {
      if (R->soul_only) { card0(&cs[i]); continue; }
      make_playing(R, prand(R, K_STDSET, R->ante) > 0.6, 1, &cs[i]);
      if (R->need_mods) {
        cs[i].ed = poll_edition(R, K_EDI_STD, R->ante, 2.0, 1);
        if (prand(R, K_STDSEAL, R->ante) > 1 - 0.02 * 10) {
          double st = prand(R, K_STDSEALTYPE, R->ante);
          cs[i].seal = st > 0.75 ? 1 : st > 0.5 ? 2 : st > 0.25 ? 3 : 4;   /* 1 red 2 blue 3 gold 4 purple */
        }
      }
    } else {
      if (R->soul_only) { card0(&cs[i]); continue; }
      make_joker(R, 1, &cs[i]);
    }
  }
  /* close: The Soul first, then --take items; remove the rest */
  for (i = 0; i < n && picks > 0; i++)
    if (cs[i].id == ID_C_SOUL && R->take_souls && free_slots(R) > 0) { taken[i] = 1; picks--; use_soul(R, &cs[i]); }
  for (i = 0; i < n && picks > 0; i++)
    if (!taken[i] && cs[i].id >= 0 && BGET(R->take, cs[i].id)) {
      if (ITEM_KIND[cs[i].id] == 1) {
        if (free_slots(R) <= 0 && cs[i].ed != 4) continue;
        taken[i] = 1; picks--; gain_joker(R, cs[i].id, cs[i].ed);
      } else { taken[i] = 1; picks--; }
    }
  for (i = 0; i < n; i++) {
    if (cs[i].id >= 0 && ITEM_KIND[cs[i].id] == 1 && taken[i]) continue;
    removed(R, cs[i].id);
  }
  for (i = 0; i < n; i++) emit_card(R, E_PACK, &cs[i]);
}

INLINE void add_tag(Run *R, int t) {
  int i, copies = 0;
  if (t != ID_TAG_DOUBLE)
    for (i = R->ntags - 1; i >= 0; i--) if (R->tags[i] == ID_TAG_DOUBLE) { del_tag(R, i); copies++; }
  push_tag(R, t);
  for (i = 0; i < copies; i++) push_tag(R, t);
}

INLINE void blind_select(Run *R) {
  int i = 0, t, k;
  R->kind = 3;
  while (i < R->ntags) {
    t = R->tags[i];
    if (TAGTYPE[t] == 5) {
      del_tag(R, i);
      if (t == ID_TAG_TOP_UP) {
        for (k = 0; k < 2; k++) if (free_slots(R) > 0) {
          Card c; make_joker(R, 4, &c); gain_joker(R, c.id, c.ed); emit(R, E_TOPUP, c.id, c.ed, 0, -1);
        }
      }
      continue;
    }
    i++;
  }
  for (i = 0; i < R->ntags; i++) {
    t = R->tags[i];
    if (TAGTYPE[t] == 4) {
      del_tag(R, i);
      if (t == ID_TAG_BOSS) R->cur_boss = new_boss(R);
      else {
        int bit = t == ID_TAG_CHARM ? 0 : t == ID_TAG_BUFFOON ? 1 : t == ID_TAG_METEOR ? 2 : t == ID_TAG_ETHEREAL ? 3 : 4;
        if (!(R->skip_tagpack & (1 << bit))) open_pack(R, TAGPACK[t]);
      }
      break;
    }
  }
}

INLINE void redeem(Run *R, int v, int in_shop) {
  BSET(R->vused, v);
  if (v == ID_V_TAROT_MERCHANT) R->r_tarot = 9.6;
  else if (v == ID_V_TAROT_TYCOON) R->r_tarot = 32;
  else if (v == ID_V_PLANET_MERCHANT) R->r_planet = 9.6;
  else if (v == ID_V_PLANET_TYCOON) R->r_planet = 32;
  else if (v == ID_V_MAGIC_TRICK || v == ID_V_ILLUSION) R->r_pc = 4;
  else if (v == ID_V_HONE) R->ed_rate = 2;
  else if (v == ID_V_GLOW_UP) R->ed_rate = 4;
  else if (v == ID_V_OVERSTOCK_NORM || v == ID_V_OVERSTOCK_PLUS) {
    R->joker_max++;
    if (in_shop && !R->soul_only)
      while (R->nsc < R->joker_max && R->nsc < MAXSHOP) { shop_slot(R, &R->sc[R->nsc]); R->sc_taken[R->nsc] = 0; R->nsc++; }
  }
}

INLINE void take_from_slots(Run *R) {
  int i;
  if (!R->ntake) return;
  for (i = 0; i < R->nsc; i++) {
    Card *c = &R->sc[i];
    if (c->id >= 0 && !R->sc_taken[i] && BGET(R->take, c->id)) {
      if (ITEM_KIND[c->id] == 1) {
        if (free_slots(R) <= 0 && c->ed != 4) continue;
        gain_joker(R, c->id, c->ed);
      }
      R->sc_taken[i] = 1;
    }
  }
}
INLINE void reroll(Run *R) {
  int i;
  for (i = 0; i < R->nsc; i++) if (!R->sc_taken[i]) removed(R, R->sc[i].id);
  R->nsc = 0;
  for (i = 0; i < R->joker_max && i < MAXSHOP; i++) { shop_slot(R, &R->sc[i]); R->sc_taken[i] = 0; R->nsc++; }
  take_from_slots(R);
}

INLINE void shop(Run *R, int g, int kind) {
  int i, j, packs[2], vs[6], nv = 0, sidx = (g - 1) * 3 + kind;
  R->g = g; R->kind = kind; R->rr = 0;
  R->nsc = 0;
  if (!R->soul_only)
    for (i = 0; i < R->joker_max && i < MAXSHOP; i++) { shop_slot(R, &R->sc[i]); R->sc_taken[i] = 0; R->nsc++; }
  if (R->cur_voucher >= 0) { vs[nv++] = R->cur_voucher; created(R, R->cur_voucher); }
  R->nsv = 0; for (i = 0; i < nv; i++) R->sv[R->nsv++] = vs[i];
  packs[0] = get_pack(R); packs[1] = get_pack(R);
  i = 0;
  while (i < R->ntags) {
    if (TAGTYPE[R->tags[i]] == 3) {
      int v; del_tag(R, i);
      v = next_voucher(R, 1);
      if (nv < 6) { vs[nv++] = v; R->sv[R->nsv++] = v; } else R->overflow = 1;
      created(R, v);
      continue;
    }
    i++;
  }
  for (i = 0; i < nv; i++) {
    int v = vs[i];
    if (BGET(R->buy, v) && !BGET(R->vused, v)) {
      if (v == R->cur_voucher) R->cur_voucher = -1;
      redeem(R, v, 1);
    }
  }
  take_from_slots(R);
  for (i = 0; i < nv; i++) emit(R, E_VOUCHER, vs[i], 0, 0, -1);
  emit(R, E_PACKTYPE, BOOST_ID[packs[0]], 0, 0, -1);
  emit(R, E_PACKTYPE, BOOST_ID[packs[1]], 0, 0, -1);
  for (i = 0; i < R->nsc; i++) emit(R, E_SHOP, R->sc[i].id, R->sc[i].ed, 0, R->sc[i].card);
  if (R->maxrr > 0 && !R->soul_only) {
    int cnt[MAXCR], k;
    Run snap = *R;
    for (k = 1; k <= R->maxrr; k++) {
      reroll(R);
      R->rr = k;
      for (i = 0; i < R->nsc; i++) emit(R, E_SHOP, R->sc[i].id, R->sc[i].ed, 0, R->sc[i].card);
    }
    for (k = 0; k < MAXCR; k++) cnt[k] = R->cnt[k];
    *R = snap;
    for (k = 0; k < MAXCR; k++) R->cnt[k] = cnt[k];
    R->rr = 0;
  }
  if (!R->soul_only)
    for (j = 0; j < (sidx < 24 ? R->rer[sidx] : 0); j++) {
      reroll(R);
      for (i = 0; i < R->nsc; i++) emit(R, E_SHOP, R->sc[i].id, R->sc[i].ed, 0, R->sc[i].card);
    }
  for (j = 0; j < 2; j++) {
    int bit = sidx * 2 + j;
    int skip = bit < 32 ? (R->skip_lo >> bit) & 1 : (bit < 64 ? (R->skip_hi >> (bit - 32)) & 1 : 0);
    if (!skip) open_pack(R, packs[j]);
  }
  for (i = 0; i < R->nsc; i++) if (!R->sc_taken[i]) removed(R, R->sc[i].id);
  for (i = 0; i < nv; i++) removed(R, vs[i]);
  R->nsc = 0; R->nsv = 0;
}

/* ---------------- setup ---------------- */
INLINE void run_init(Run *R, const u8 *seed, int slen, CPARAM int *cfg, CPARAM Crit *cr, int ncr) {
  int i, p, n;
  R->slen = slen; for (i = 0; i < slen; i++) R->seed[i] = seed[i];
  R->sdv = 0; R->n = 0; R->overflow = 0;
  for (i = 0; i < 512; i++) R->hix[i] = 0;
  {  /* pseudohash(seed) */
    double num = 1.0;
    for (i = slen; i >= 1; i--) { num = ((1.1239285023 / num) * (double)seed[i-1] * PI_D + PI_D * (double)i); num = num - floor(num); }
    R->hs = num;
  }
  R->sdv = 0;
  for (i = 0; i < N_WORDS; i++) { R->used[i] = 0; R->vused[i] = 0; R->take[i] = 0; R->buy[i] = 0; R->locked[i] = 0; }
  R->nj = 0; R->ntags = 0; R->nsc = 0; R->nsv = 0;
  for (i = 0; i < N_BLINDS; i++) R->boss_used[i] = 0;
  R->r_joker = 20; R->r_tarot = 4; R->r_planet = 4; R->r_pc = 0; R->r_spec = 0; R->ed_rate = 1;
  R->joker_max = 2; R->first_buf = 0; R->cur_voucher = -1; R->cur_boss = -1;
  R->ante = 1; R->g = 1; R->kind = 0; R->rr = 0;
  R->mode = cfg[CFG_MODE]; R->played = cfg[CFG_PLAYED]; R->deck = cfg[CFG_DECK];
  R->take_souls = cfg[CFG_TAKE_SOULS]; R->most_planet = cfg[CFG_MOST_PLANET];
  R->skips = cfg[CFG_SKIPS]; R->skip_tagpack = cfg[CFG_SKIP_TAGPACK];
  R->skip_lo = (u32)cfg[CFG_SKIP_PACK_LO]; R->skip_hi = (u32)cfg[CFG_SKIP_PACK_HI];
  for (i = 0; i < 24; i++) R->rer[i] = cfg[CFG_RER + i];
  p = CFG_LISTS;
  n = cfg[p++]; R->ntake = n; for (i = 0; i < n; i++) { int v = cfg[p++]; BSET(R->take, v); }
  n = cfg[p++]; for (i = 0; i < n; i++) { int v = cfg[p++]; BSET(R->buy, v); }
  R->joker_slots = 5 + (R->deck == 5 ? 1 : 0) - (R->deck == 6 ? 1 : 0);
  /* deck */
  if (R->deck == 1) { R->r_spec = 2; if (cfg[CFG_START_HELD]) BSET(R->used, ID_C_HEX); }
  if (R->deck == 2) { redeem(R, ID_V_CRYSTAL_BALL, 0); if (cfg[CFG_START_HELD]) BSET(R->used, ID_C_FOOL); }
  if (R->deck == 3) redeem(R, ID_V_TELESCOPE, 0);
  if (R->deck == 4) { redeem(R, ID_V_TAROT_MERCHANT, 0); redeem(R, ID_V_PLANET_MERCHANT, 0); redeem(R, ID_V_OVERSTOCK_NORM, 0); }
  n = cfg[p++]; for (i = 0; i < n; i++) { int v = cfg[p++]; gain_joker(R, v, 0); }
  n = cfg[p++]; for (i = 0; i < n; i++) { int v = cfg[p++]; BSET(R->locked, v); }
  R->cr = cr; R->ncr = ncr; R->maxrr = 0; R->need_mods = 0; R->trace = 0; R->no_packs = 0; R->no_ed = 0;
  for (i = 0; i < MAXCR; i++) R->cnt[i] = 0;
  { int lite = R->ntake == 0, any = 0;
    for (i = 0; i < ncr; i++) {
      if (cr[i].rerolls > R->maxrr) R->maxrr = cr[i].rerolls;
      if ((cr[i].loc == C_PACK || cr[i].loc == C_CARD || cr[i].loc == C_SHOP || cr[i].loc == C_JOKER) && (cr[i].edition || cr[i].seal)) R->need_mods = 1;
      if (cr[i].loc == C_LEGEND) any = 1;
      else if (cr[i].loc == C_PACK && (cr[i].id == ID_C_SOUL || cr[i].id == ID_C_BLACK_HOLE) && !cr[i].edition && !cr[i].seal) any = 1;
      else if (cr[i].loc == C_SHOP || cr[i].loc == C_PACK || cr[i].loc == C_JOKER || cr[i].loc == C_CARD) lite = 0;
    }
#ifdef NO_LITE
    R->soul_only = 0; (void)lite; (void)any;
#else
    R->soul_only = lite && any;
#endif
    { int np = R->ntake == 0, ned = R->ntake == 0;
      for (i = 0; i < ncr; i++) {
        if (cr[i].loc == C_PACK || cr[i].loc == C_LEGEND || cr[i].loc == C_JOKER || cr[i].loc == C_CARD) np = 0;
        if (cr[i].edition) ned = 0;
      }
#ifdef NO_LITE
      np = 0;
#endif
      R->no_packs = np; R->no_ed = np && ned;
    }
  }
}

/* simulate up to `antes` game antes; returns 1 match, 0 no match, 2 unsure (internal table overflow -> verify on CPU) */
INLINE int simulate(Run *R, int antes) {
  int g, k, c, tags[2];
  R->ante = 1;
  R->cur_boss = new_boss(R);
  R->cur_voucher = next_voucher(R, 0);
  tags[0] = next_tag(R); tags[1] = next_tag(R);
  R->g = 1; blind_select(R);
  for (g = 1; g <= antes; g++) {
    R->g = g; R->kind = 3; R->rr = 0;
    emit(R, E_TAG, tags[0], 0, 0, -1); emit(R, E_TAG, tags[1], 0, 0, -1);
    for (k = 0; k < 2; k++) {
      if ((g - 1) * 3 + k < 31 && (R->skips & (1 << ((g - 1) * 3 + k)))) { R->g = g; add_tag(R, tags[k]); blind_select(R); }
      else { shop(R, g, k); R->g = g; blind_select(R); }
    }
    R->g = g; R->kind = 3;
    emit(R, E_BOSS, R->cur_boss, 0, 0, -1);
    { /* drop streams of antes that can never be used again */
      int w = 0, i;
      for (i = 0; i < R->n; i++) {
        int kind = R->sid[i] / (256 * ABASE), an = (R->sid[i] / 256) % ABASE;
        if (!KEY_HAS_ANTE[kind] || an > g) { R->sid[w] = R->sid[i]; R->st[w] = R->st[i]; w++; }
      }
      R->n = w;
      for (i = 0; i < 512; i++) R->hix[i] = 0;
      for (i = 0; i < w; i++) { u32 h = ((u32)R->sid[i] * 2654435761u) >> 23; while (R->hix[h]) h = (h + 1) & 511; R->hix[h] = (short)(i + 1); }
    }
    R->ante = g + 1;
    R->cur_voucher = next_voucher(R, 0);
    tags[0] = next_tag(R); tags[1] = next_tag(R);
    shop(R, g, 2);
    R->cur_boss = new_boss(R);
    R->g = g; blind_select(R);
    for (c = 0; c < R->ncr; c++) if (R->cr[c].hi <= g && R->cnt[c] < R->cr[c].count) return R->overflow ? 2 : 0;
  }
  for (c = 0; c < R->ncr; c++) if (R->cnt[c] < R->cr[c].count) return R->overflow ? 2 : 0;
  return R->overflow ? 2 : 1;
}
