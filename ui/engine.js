/* Balatro seed engine - JavaScript port of engine.py (+ the parts of bridge.py the finder needs).
   Same RNG call order as engine.py; checked event-by-event against it by difftest_js.py.
   Usage: const E = BalatroEngine(DATA);  works in browsers, Web Workers and node. */
(function (root) {
'use strict';
function BalatroEngine(DATA) {
const SEED_CHARS = '123456789ABCDEFGHIJKLMNPQRSTUVWXYZ';
const PI = Math.PI;
const C = DATA.centers;

/* ------------------------------------------------------------------ LuaJIT PRNG (64-bit Tausworthe, as 32-bit halves) */
const f64 = new Float64Array(1), u32 = new Uint32Array(f64.buffer);   // little-endian: u32[0] = low, u32[1] = high
class LuaRandom {
  constructor() { this.h = new Uint32Array(4); this.l = new Uint32Array(4); }
  _gen(i, k, q, s) {
    // z = (((z<<q)^z) >> (k-s)) ^ ((z & (~0 << (64-k))) << s)
    let zh = this.h[i], zl = this.l[i];
    // a = (z << q) ^ z      (q < 32)
    let ah = ((zh << q) | (zl >>> (32 - q))) ^ zh, al = (zl << q) ^ zl;
    ah >>>= 0; al >>>= 0;
    // b = a >>> (k-s)
    const r = k - s; let bh, bl;
    if (r >= 32) { bl = ah >>> (r - 32); bh = 0; } else { bl = ((al >>> r) | (ah << (32 - r))) >>> 0; bh = ah >>> r; }
    // c = (z & mask) << s, mask clears the low (64-k) bits; 64-k < 32 for all four generators
    const m = 64 - k;
    let ml = (zl >>> m) << m; ml >>>= 0;
    let ch, cl;
    if (s >= 32) { ch = ml << (s - 32); cl = 0; } else { ch = ((zh << s) | (ml >>> (32 - s))) >>> 0; cl = (ml << s) >>> 0; }
    zh = (bh ^ ch) >>> 0; zl = (bl ^ cl) >>> 0;
    this.h[i] = zh; this.l[i] = zl;
  }
  _step() {
    this._gen(0, 63, 31, 18); this._gen(1, 58, 19, 28); this._gen(2, 55, 24, 7); this._gen(3, 47, 21, 8);
    this.rh = (this.h[0] ^ this.h[1] ^ this.h[2] ^ this.h[3]) >>> 0;
    this.rl = (this.l[0] ^ this.l[1] ^ this.l[2] ^ this.l[3]) >>> 0;
  }
  seed(d) {
    let r = 0x11090601;
    for (let i = 0; i < 4; i++) {
      const sh = r & 255; r >>>= 8;
      d = d * PI + 2.7182818284590452354;
      f64[0] = d;
      let hi = u32[1], lo = u32[0];
      // m = 1 << sh  (sh is 1, 6, 9, 17: lives in the low word)
      const m = (1 << sh) >>> 0;
      if (hi === 0 && lo < m) { lo = (lo + m) >>> 0; }
      this.h[i] = hi; this.l[i] = lo;
    }
    for (let i = 0; i < 10; i++) this._step();
  }
  random() {
    this._step();
    u32[1] = ((this.rh & 0x000fffff) | 0x3ff00000) >>> 0; u32[0] = this.rl;
    return f64[0] - 1.0;
  }
  randint(n) { return Math.floor(this.random() * n) + 1; }
}

/* ------------------------------------------------------------------ pseudohash / pseudoseed */
function pseudohash(s) {
  let num = 1;
  for (let i = s.length; i >= 1; i--) num = ((1.1239285023 / num) * s.charCodeAt(i - 1) * PI + PI * i) % 1;
  return num;
}
const SPLIT = 134217729; // 2^27 + 1
const T13 = 1e13, T13H = (SPLIT * T13) - ((SPLIT * T13) - T13), T13L = T13 - T13H;
function round13(v) {           // == tonumber(string.format("%.13f", v)) for 0 <= v < 1: exact, ties to even
  const hi = v * T13;
  const c = SPLIT * v, vh = c - (c - v), vl = v - vh;
  const lo = ((vh * T13H - hi) + vh * T13L + vl * T13H) + vl * T13L;   // exact error of v*1e13 (Dekker)
  const f = Math.floor(hi);
  const frac = (hi - f) + lo;
  let k = f;
  if (frac > 0.5) k = f + 1; else if (frac === 0.5 && f % 2 === 1) k = f + 1; else if (frac < -0.5) k = f - 1;
  return k / T13;
}
function stepState(x) { return Math.abs(round13((2.134453429141 + x * 1.72431234) % 1)); }

/* ------------------------------------------------------------------ constants */
const PACK_TAGS = {tag_charm: 'p_arcana_mega_1', tag_buffoon: 'p_buffoon_mega_1', tag_meteor: 'p_celestial_mega_1',
                   tag_ethereal: 'p_spectral_normal_1', tag_standard: 'p_standard_mega_1'};
const TAG_TYPE = {tag_uncommon: 'store_joker_create', tag_rare: 'store_joker_create',
  tag_negative: 'store_joker_modify', tag_foil: 'store_joker_modify', tag_holo: 'store_joker_modify', tag_polychrome: 'store_joker_modify',
  tag_investment: 'eval', tag_voucher: 'voucher_add', tag_boss: 'new_blind_choice', tag_standard: 'new_blind_choice',
  tag_charm: 'new_blind_choice', tag_meteor: 'new_blind_choice', tag_buffoon: 'new_blind_choice', tag_ethereal: 'new_blind_choice',
  tag_handy: 'immediate', tag_garbage: 'immediate', tag_top_up: 'immediate', tag_skip: 'immediate', tag_orbital: 'immediate',
  tag_economy: 'immediate', tag_coupon: 'shop_final_pass', tag_double: 'tag_add', tag_juggle: 'round_start_bonus', tag_d_six: 'shop_start'};
const SHOP_LABEL = {s: 'after Small Blind', b: 'after Big Blind', x: 'after Boss Blind'};
const SELL_EFFECT = {   // sell effects described but not simulated (no card is created from them)
  j_luchador: 'Disables the current Boss Blind.',
  j_mr_bones: 'Prevents one death, then is destroyed.',
  j_turtle_bean: 'Its hand-size bonus is gone.'
};
const STAKES = ['White', 'Red', 'Green', 'Black', 'Blue', 'Purple', 'Orange', 'Gold'];
const BOSS_KEYS = Object.keys(DATA.blinds).filter(k => DATA.blinds[k].b);
const BOSS_SORTED = BOSS_KEYS.slice().sort();
const centerOf = k => C[k];
function poolCenters(list) { return list.map(k => Object.assign({key: k}, C[k])); }
const POOL = {}; for (const s in DATA.pool) POOL[s] = poolCenters(DATA.pool[s]);
const RARITY = {}; for (const r in DATA.rarity) RARITY[r] = poolCenters(DATA.rarity[r]);
const TAG_POOL = DATA.tag_pool.map(k => ({key: k, rq: DATA.tags[k].rq, m: DATA.tags[k].m}));
const BOOSTERS = POOL.Booster;
const PLANET_BY_HAND = {}; for (const k in C) if (C[k].s === 'Planet' && C[k].h) PLANET_BY_HAND[C[k].h] = k;

function deepClone(o) { return typeof structuredClone === 'function' ? structuredClone(o) : JSON.parse(JSON.stringify(o)); }

/* ------------------------------------------------------------------ Run */
class Run {
  constructor(seed, o) {
    o = o || {};
    this.seed = seed.toUpperCase();
    this.unlocked_mode = o.unlocked === 'fresh' ? 'fresh' : 'all';
    this.locked = new Set(o.locked || []);
    this.stake = o.stake || 1;
    this.planets_played = !!o.planets_played;
    this.take = new Set(o.take || []);
    this.take_souls = o.take_souls !== false;
    this.most_played = o.most_played || null;
    this.buy_vouchers = new Set(o.buy_vouchers || []);
    this.skips = new Set(o.skips || []);
    this.rerolls = Object.assign({}, o.rerolls || {});
    this.skip_packs = new Set(o.skip_packs || []);
    this.plan = o.plan || {};            // analyzer: shop id -> ordered list of actions (reroll, voucher, pack, buy, use, sell)
    this.preview_rerolls = o.preview_rerolls || 0;
    /* analyzer-only "what I actually did" mode: per-card picks, card effects, held consumables, Perkeo */
    this.interactive = !!o.interactive;
    this.picks = Object.assign({}, o.picks || {});          // card id -> true (take/use) | false (decline)
    this.cons = [];                                         // consumables you hold
    this.last_tp = null;                                    // last Tarot/Planet used (for The Fool)
    this.perkeo_n = o.perkeo_copies ? +o.perkeo_copies : null;
    this.ctx = 'start'; this.tagPackN = 0; this.curSid = null; this.pairIdx = 0;
    this.sells = o.sells || {}; this.uses = o.uses || {}; this._jseq = 0;
    this.warnings = [];
    this.rng = new LuaRandom();
    this.streams = new Map();
    this.hashed_seed = pseudohash(this.seed);
    this.ante = 1;
    this.used = new Set();
    this.jokers = [];
    this.consumables = [];
    this.used_vouchers = new Set();
    this.tags = [];
    this.bosses_used = {}; for (const k of BOSS_KEYS) this.bosses_used[k] = 0;
    this.joker_rate = 20; this.tarot_rate = 4; this.planet_rate = 4;
    this.playing_card_rate = 0; this.spectral_rate = 0;
    this.edition_rate = 1;
    this.joker_max = 2;
    const deck = o.deck && C[o.deck] ? o.deck : 'b_red';
    this.joker_slots = 5 + (deck === 'b_black' ? 1 : deck === 'b_painted' ? -1 : 0);
    this.first_shop_buffoon = false;
    this.shop_voucher_keys = new Set();
    this.shop_cards = null;
    this.deck = deck;
    this._applyDeck(deck, o.start_consumables === 'used' ? 'used' : 'held');
    (o.own || []).forEach((k, i) => this._gainJoker({type: 'Joker', key: k, name: C[k].n, id: 'own.' + i}));
  }
  _applyDeck(deck, sc) {
    const cfg = {b_ghost: {spectral_rate: 2, consumables: ['c_hex']}, b_magic: {vouchers: ['v_crystal_ball'], consumables: ['c_fool', 'c_fool']},
                 b_nebula: {vouchers: ['v_telescope']}, b_zodiac: {vouchers: ['v_tarot_merchant', 'v_planet_merchant', 'v_overstock_norm']}}[deck] || {};
    if (cfg.spectral_rate !== undefined) this.spectral_rate = cfg.spectral_rate;
    for (const v of cfg.vouchers || []) this.redeemVoucher(v, false);
    if (sc === 'held') (cfg.consumables || []).forEach((c, i) => {
      this.consumables.push(c); this.used.add(c);
      if (this.interactive) this.cons.push({type: C[c].s, key: c, name: C[c].n, id: 'start.' + i});
    });
  }
  redeemVoucher(v, inShop) {
    this.used_vouchers.add(v);
    if (v === 'v_tarot_merchant') this.tarot_rate = 9.6;
    else if (v === 'v_tarot_tycoon') this.tarot_rate = 32;
    else if (v === 'v_planet_merchant') this.planet_rate = 9.6;
    else if (v === 'v_planet_tycoon') this.planet_rate = 32;
    else if (v === 'v_magic_trick' || v === 'v_illusion') this.playing_card_rate = 4;
    else if (v === 'v_hone') this.edition_rate = 2;
    else if (v === 'v_glow_up') this.edition_rate = 4;
    else if (v === 'v_overstock_norm' || v === 'v_overstock_plus') {
      this.joker_max += 1;
      if (inShop && this.shop_cards !== null && !(this.fast && this.fast.soulOnly)) while (this.shop_cards.length < this.joker_max) this.shop_cards.push(this.shopSlot());
    }
  }
  /* RNG */
  pseudoseed(key) {
    let st = this.streams.get(key);
    if (st === undefined) st = pseudohash(key + this.seed);
    st = stepState(st);
    this.streams.set(key, st);
    return (st + this.hashed_seed) / 2;
  }
  pseudorandom(k) { const s = typeof k === 'string' ? this.pseudoseed(k) : k; this.rng.seed(s); return this.rng.random(); }
  pickIndex(n, sv) { this.rng.seed(sv); return this.rng.randint(n); }
  /* existence */
  showman() { return this.jokers.some(j => j.key === 'j_ring_master'); }
  _created(k) { this.used.add(k); }
  _removed(k) { if (!this.jokers.some(j => j.key === k)) this.used.delete(k); }
  _free() { let neg = 0; for (const j of this.jokers) if (j.edition === 'negative') neg++; return this.joker_slots + neg - this.jokers.length; }
  _gainJoker(c) { if (this.interactive && !c.id) c.id = 'g' + (++this._jseq); this.jokers.push(c); this.used.add(c.key); }
  _unlockOk(v) { if (this.locked.has(v.key)) return false; return this.unlocked_mode === 'all' || v.u !== false || v.r === 4; }
  /* pools */
  getCurrentPool(typ, rarity, legendary, append) {
    const ante = this.ante; append = append || '';
    let starting, poolKey;
    if (typ === 'Joker') {
      const r = rarity !== undefined && rarity !== null ? rarity : this.pseudorandom('rarity' + ante + append);
      const rr = legendary ? 4 : (r > 0.95 ? 3 : (r > 0.7 ? 2 : 1));
      starting = RARITY[rr]; poolKey = 'Joker' + rr + (legendary ? '' : append);
    } else if (typ === 'Tag') { starting = TAG_POOL; poolKey = 'Tag' + append; }
    else { starting = POOL[typ]; poolKey = typ + append; }
    const sm = this.showman();
    const pool = []; let size = 0;
    for (const v of starting) {
      let add = false;
      if (typ === 'Tag') {
        if ((!v.rq || this.unlocked_mode === 'all') && (!v.m || v.m <= ante)) add = true;
      } else if (typ === 'Enhanced') add = true;
      else if (!(this.used.has(v.key) && !sm) && this._unlockOk(v)) {
        if (v.s === 'Voucher') {
          if (!this.used_vouchers.has(v.key)) {
            let inc = (v.rq || []).every(q => this.used_vouchers.has(q));
            if (this.shop_voucher_keys.has(v.key)) inc = false;
            if (inc) add = true;
          }
        } else if (v.s === 'Planet') { if (!v.sl || this.planets_played) add = true; }
        else if (v.eg) add = false;
        else add = true;
        if (v.n === 'Black Hole' || v.n === 'The Soul') add = false;
      }
      if (v.yp) add = false;
      if (add) { pool.push(v.key); size++; } else pool.push('UNAVAILABLE');
    }
    if (size === 0) pool.splice(0, pool.length, ({Tarot: 'c_strength', Planet: 'c_pluto', Spectral: 'c_incantation', Joker: 'j_joker', Voucher: 'v_blank', Tag: 'tag_handy'})[typ] || 'j_joker');
    return [pool, poolKey + (legendary ? '' : String(ante))];
  }
  /* availability of one pool entry (same rules as getCurrentPool) */
  _avail(typ, v, sm) {
    if (v.yp) return false;
    if (typ === 'Tag') return (!v.rq || this.unlocked_mode === 'all') && (!v.m || v.m <= this.ante);
    if (typ === 'Enhanced') return true;
    if ((this.used.has(v.key) && !sm) || !this._unlockOk(v)) return false;
    if (v.n === 'Black Hole' || v.n === 'The Soul') return false;
    if (v.s === 'Voucher') {
      if (this.used_vouchers.has(v.key) || this.shop_voucher_keys.has(v.key)) return false;
      return (v.rq || []).every(q => this.used_vouchers.has(q));
    }
    if (v.s === 'Planet') return !v.sl || this.planets_played;
    if (v.eg) return false;
    return true;
  }
  /* getCurrentPool + drawFromPool without building the pool: draw first, check availability only when needed */
  draw(typ, rarity, legendary, append, keyOverride) {
    const ante = this.ante; append = append || '';
    let starting, key;
    if (typ === 'Joker') {
      const r = rarity !== undefined && rarity !== null ? rarity : this.pseudorandom('rarity' + ante + append);
      const rr = legendary ? 4 : (r > 0.95 ? 3 : (r > 0.7 ? 2 : 1));
      starting = RARITY[rr]; key = 'Joker' + rr + (legendary ? '' : append + ante);
    } else if (typ === 'Tag') { starting = TAG_POOL; key = 'Tag' + append + ante; }
    else { starting = POOL[typ]; key = typ + append + ante; }
    if (keyOverride) key = keyOverride;
    const sm = this.showman(), n = starting.length;
    let v = starting[this.pickIndex(n, this.pseudoseed(key)) - 1];
    if (this._avail(typ, v, sm)) return v.key;
    if (!starting.some(x => this._avail(typ, x, sm)))
      return ({Tarot: 'c_strength', Planet: 'c_pluto', Spectral: 'c_incantation', Joker: 'j_joker', Voucher: 'v_blank', Tag: 'tag_handy'})[typ] || 'j_joker';
    let it = 1;
    for (;;) { it++; v = starting[this.pickIndex(n, this.pseudoseed(key + '_resample' + it)) - 1]; if (this._avail(typ, v, sm)) return v.key; }
  }
  drawFromPool(pool, key) {
    let c = pool[this.pickIndex(pool.length, this.pseudoseed(key)) - 1], it = 1;
    while (c === 'UNAVAILABLE') { it++; c = pool[this.pickIndex(pool.length, this.pseudoseed(key + '_resample' + it)) - 1]; }
    return c;
  }
  pollEdition(key, mod, noNeg, guaranteed) {
    mod = mod || 1;
    const p = this.pseudorandom(key);
    if (guaranteed) {
      if (p > 1 - 0.003 * 25 && !noNeg) return 'negative';
      if (p > 1 - 0.006 * 25) return 'polychrome';
      if (p > 1 - 0.02 * 25) return 'holo';
      if (p > 1 - 0.04 * 25) return 'foil';
      return null;
    }
    if (p > 1 - 0.003 * mod && !noNeg) return 'negative';
    if (p > 1 - 0.006 * this.edition_rate * mod) return 'polychrome';
    if (p > 1 - 0.02 * this.edition_rate * mod) return 'holo';
    if (p > 1 - 0.04 * this.edition_rate * mod) return 'foil';
    return null;
  }
  createCard(typ, area, legendary, rarity, soulable, forced, append) {
    const ante = this.ante; append = append || '';
    const sm = this.showman();
    if (!forced && soulable) {
      if ((typ === 'Tarot' || typ === 'Spectral' || typ === 'Tarot_Planet') && !(this.used.has('c_soul') && !sm))
        if (this.pseudorandom('soul_' + typ + ante) > 0.997) forced = 'c_soul';
      if ((typ === 'Planet' || typ === 'Spectral') && !(this.used.has('c_black_hole') && !sm))
        if (this.pseudorandom('soul_' + typ + ante) > 0.997) forced = 'c_black_hole';
    }
    if (typ === 'Base') forced = 'c_base';
    let key;
    if (forced) { key = forced; if (C[key].s !== 'Default') typ = C[key].s; }
    else if (this.fast && this.fast.soulOnly && typ !== 'Joker') key = null;
    else key = this.draw(typ, rarity, legendary, append);
    if (key === null) return {type: typ, key: null, name: ''};
    const card = {type: typ, key, name: C[key].n};
    if (typ === 'Base' || typ === 'Enhanced') {
      const keys = DATA.card_keys;
      const ck = keys[this.pickIndex(keys.length, this.pseudoseed('front' + append + ante)) - 1];
      card.card = DATA.cards[ck]; card.card_key = ck;
    }
    this._created(key);
    if (typ === 'Joker' && this.fast) {           // search fast path: stickers never change which cards appear
      const ed = this.fast.noEd && area !== 'jokers' ? null : this.pollEdition('edi' + append + ante);
      if (ed) card.edition = ed;
      return card;
    }
    if (typ === 'Joker') {
      if (area === 'shop' || area === 'pack') {
        const poll = this.pseudorandom((area === 'pack' ? 'packetper' : 'etperpoll') + ante);
        if (this.stake >= 4 && poll > 0.7) card.sticker = 'eternal';
        else if (this.stake >= 7 && poll > 0.4 && poll <= 0.7) card.sticker = 'perishable';
        if (this.stake >= 8 && this.pseudorandom((area === 'pack' ? 'packssjr' : 'ssjr') + ante) > 0.7) card.rental = true;
      }
      const ed = this.pollEdition('edi' + append + ante);
      if (ed) card.edition = ed;
    }
    return card;
  }
  shopSlot() {
    for (let i = 0; i < this.tags.length; i++) {
      const t = this.tags[i];
      if (TAG_TYPE[t] === 'store_joker_create') {
        const card = t === 'tag_uncommon' ? this.createCard('Joker', 'shop', false, 0.9, false, null, 'uta')
                                          : this.createCard('Joker', 'shop', false, 1, false, null, 'rta');
        card.from_tag = DATA.tags[t].n;
        this.tags.splice(i, 1);
        this._modifyTags(card);
        return card;
      }
    }
    const total = this.joker_rate + this.tarot_rate + this.planet_rate + this.playing_card_rate + this.spectral_rate;
    const polled = this.pseudorandom(this.pseudoseed('cdt' + this.ante)) * total;
    const illusion = this.used_vouchers.has('v_illusion');
    let pcType = 'Base';
    if (illusion && this.pseudorandom(this.pseudoseed('illusion')) > 0.6) pcType = 'Enhanced';
    let check = 0;
    for (const [typ, val] of [['Joker', this.joker_rate], ['Tarot', this.tarot_rate], ['Planet', this.planet_rate], [pcType, this.playing_card_rate], ['Spectral', this.spectral_rate]]) {
      if (polled > check && polled <= check + val) {
        const card = this.createCard(typ, 'shop', false, null, false, null, 'sho');
        this._modifyTags(card);
        if ((typ === 'Base' || typ === 'Enhanced') && illusion && this.pseudorandom(this.pseudoseed('illusion')) > 0.8) {
          const ep = this.pseudorandom(this.pseudoseed('illusion'));
          card.edition = ep > 1 - 0.15 ? 'polychrome' : (ep > 0.5 ? 'holo' : 'foil');
        }
        return card;
      }
      check += val;
    }
    return null;
  }
  _modifyTags(card) {
    if (card.type !== 'Joker' || card.edition) return;
    for (let i = 0; i < this.tags.length; i++) {
      const t = this.tags[i];
      if (TAG_TYPE[t] === 'store_joker_modify') { card.edition = t.slice(4); card.edition_from_tag = true; this.tags.splice(i, 1); return; }
    }
  }
  nextVoucher(fromTag) { return this.draw('Voucher', null, false, '', fromTag ? 'Voucher_fromtag' : null); }
  nextTag() { return this.draw('Tag', null, false, ''); }
  getPack() {
    if (!this.first_shop_buffoon) { this.first_shop_buffoon = true; return Object.assign({key: 'p_buffoon_normal_1'}, C.p_buffoon_normal_1); }
    let cume = 0; for (const v of BOOSTERS) cume = cume + (v.w || 1);
    const poll = this.pseudorandom(this.pseudoseed('shop_pack' + this.ante)) * cume;
    let it = 0;
    for (const v of BOOSTERS) { it = it + (v.w || 1); if (it >= poll && it - (v.w || 1) <= poll) return v; }
    return null;
  }
  newBoss() {
    const a = this.ante, a1 = Math.max(1, a);
    const elig = [];
    let minUse = 100;
    for (const k of BOSS_KEYS) {
      const [mn, , sd] = DATA.blinds[k].b;
      let ok = false;
      if (!sd && mn <= a1 && ((a1 % 8 !== 0) || a < 2)) ok = true;
      else if (sd && a % 8 === 0 && a >= 2) ok = true;
      if (ok) { elig.push(k); if (this.bosses_used[k] <= minUse) minUse = this.bosses_used[k]; }
    }
    const set = new Set(elig.filter(k => this.bosses_used[k] <= minUse));
    const keys = BOSS_SORTED.filter(k => set.has(k));
    const k = keys[this.pickIndex(keys.length, this.pseudoseed('boss')) - 1];
    this.bosses_used[k] += 1;
    return k;
  }
  openPack(b) {
    const kind = b.k, n = b.e || 2, ante = this.ante, cards = [];
    if (this.fast && this.fast.noPacks) return cards;
    if (this.fast && this.fast.soulOnly && (kind === 'Standard' || kind === 'Buffoon')) return cards;
    for (let i = 0; i < n; i++) {
      let c;
      if (kind === 'Arcana') {
        if (this.used_vouchers.has('v_omen_globe') && this.pseudorandom('omen_globe') > 0.8) c = this.createCard('Spectral', 'pack', false, null, true, null, 'ar2');
        else c = this.createCard('Tarot', 'pack', false, null, true, null, 'ar1');
      } else if (kind === 'Celestial') {
        let forced = null;
        if (this.used_vouchers.has('v_telescope') && i === 0) {
          if (this.most_played) forced = PLANET_BY_HAND[this.most_played];
          else this._warn('Telescope is owned but no most played hand is set: the first Celestial card is shown as a normal draw.');
        }
        c = this.createCard('Planet', 'pack', false, null, true, forced, 'pl1');
      } else if (kind === 'Spectral') c = this.createCard('Spectral', 'pack', false, null, true, null, 'spe');
      else if (kind === 'Standard') {
        const typ = this.pseudorandom(this.pseudoseed('stdset' + ante)) > 0.6 ? 'Enhanced' : 'Base';
        c = this.createCard(typ, 'pack', false, null, true, null, 'sta');
        if (this.fast && !this.fast.mods) { cards.push(c); continue; }
        const ed = this.pollEdition('standard_edition' + ante, 2, true);
        if (ed) c.edition = ed;
        if (this.pseudorandom(this.pseudoseed('stdseal' + ante)) > 1 - 0.02 * 10) {
          const st = this.pseudorandom(this.pseudoseed('stdsealtype' + ante));
          c.seal = st > 0.75 ? 'Red' : st > 0.5 ? 'Blue' : st > 0.25 ? 'Gold' : 'Purple';
        }
      } else c = this.createCard('Joker', 'pack', false, null, true, null, 'buf');
      cards.push(c);
    }
    return cards;
  }
  closePack(b, cards) {
    let picks = b.c || 1;
    const decl = c => this.interactive && this.picks[c.id] === false;
    if (this.interactive) for (const c of cards) {
      const pv = this.picks[c.id];
      if (c.taken || (pv !== true && pv !== 'hold')) continue;
      if (picks <= 0) { c.note = `This pack only lets you pick ${b.c || 1}`; continue; }
      if (pv === 'hold') { if (this._holdConsumable(c)) picks--; }
      else if (this._takeCard(c)) picks--;
    }
    for (const c of cards) {
      if (picks <= 0) break;
      if (c.key === 'c_soul' && !c.taken && !decl(c) && this.take_souls && this._free() > 0) { c.taken = true; c.auto = 'soul'; picks--; c.soul_gives = this.useSoul(); }
    }
    for (const c of cards) {
      if (picks <= 0) break;
      if (!c.taken && !decl(c) && this.take.has(c.key)) {
        if (c.type === 'Joker') {
          if (this._free() <= 0 && c.edition !== 'negative') continue;
          c.taken = true; c.auto = 'take'; picks--; this._gainJoker(c);
        } else { c.taken = true; c.auto = 'take'; picks--; }
      }
    }
    for (const c of cards) { if ((c.type === 'Joker' && c.taken) || c.held) continue; this._removed(c.key); }
  }
  useSoul() { const L = this.createCard('Joker', 'jokers', true, null, false, null, 'sou'); this._gainJoker(L); return L; }

  /* ---------- analyzer-only: taking a specific card, and what using it does ---------- */
  _consFree() { let neg = 0; for (const c of this.cons) if (c.edition === 'negative') neg++; return 2 + neg - this.cons.length; }
  _takeCard(c) {
    if (c.key === 'c_soul') {
      if (this._free() <= 0) { c.note = 'No free joker slot for the legendary'; return false; }
      c.taken = true; c.soul_gives = this.useSoul(); c.soul_gives.id = c.id + '.leg'; return true;
    }
    if (c.type === 'Joker') {
      if (this._free() <= 0 && c.edition !== 'negative') { c.note = 'No free joker slot'; return false; }
      c.taken = true; this._gainJoker(c); return true;
    }
    if (c.type === 'Tarot' || c.type === 'Planet' || c.type === 'Spectral') {
      const r = this.useConsumable(c);
      c.result = r;
      if (r.fail) { c.note = r.text; return false; }
      c.taken = true; return true;
    }
    c.taken = true; c.result = {text: 'Added to your deck'}; return true;
  }
  _gainCons(card) {                       // a consumable created into your consumable slots
    card.created = true;
    if (this.picks[card.id] === true) {   // you used it right away
      card.used = true; card.result = this.useConsumable(card);
      if (card.result.fail) { card.used = false; this.cons.push(card); }
    } else this.cons.push(card);
  }
  _destroyJoker(j) { const i = this.jokers.indexOf(j); if (i >= 0) this.jokers.splice(i, 1); this._removed(j.key); }
  useConsumable(c) {
    const k = c.key, cen = C[k], id = c.id || 'card', out = {created: [], jokers: []};
    const editionless = () => this.jokers.filter(j => !j.edition);
    const fail = t => ({fail: true, text: t});
    const ci = this.cons.indexOf(c); if (ci >= 0) this.cons.splice(ci, 1);
    let r;
    if (k === 'c_emperor' || k === 'c_high_priestess') {
      const n = Math.min(2, this._consFree());
      for (let i = 0; i < n; i++) {
        const nc = this.createCard(k === 'c_emperor' ? 'Tarot' : 'Planet', 'consumeables', false, null, false, null, k === 'c_emperor' ? 'emp' : 'pri');
        nc.id = `${id}.c${i}`; out.created.push(nc); this._gainCons(nc);
      }
      out.text = n ? `Creates ${out.created.map(x => x.name).join(' and ')}` : 'No free consumable slot, so nothing is created';
      r = out;
    } else if (k === 'c_fool') {
      if (!this.last_tp) r = fail('The Fool needs a Tarot or Planet used earlier in this run');
      else if (this._consFree() <= 0) r = Object.assign(out, {text: 'No free consumable slot, so nothing is created'});
      else { const nc = this.createCard(C[this.last_tp].s, 'consumeables', false, null, false, this.last_tp, 'fool'); nc.id = `${id}.c0`; out.created.push(nc); this._gainCons(nc); out.text = `Creates ${nc.name} (the last Tarot or Planet you used)`; r = out; }
    } else if (k === 'c_judgement' || k === 'c_wraith') {
      if (this._free() <= 0) r = fail('Needs a free joker slot');
      else {
        const j = this.createCard('Joker', 'jokers', false, k === 'c_wraith' ? 0.99 : null, false, null, k === 'c_wraith' ? 'wra' : 'jud');
        j.id = id + '.j'; this._gainJoker(j); out.jokers.push(j);
        out.text = `Creates ${j.name}${j.edition ? ' (' + j.edition + ')' : ''}` + (k === 'c_wraith' ? ' and sets your money to $0' : ''); r = out;
      }
    } else if (k === 'c_wheel_of_fortune') {
      const el = editionless();
      if (!el.length) r = fail('Needs a joker without an edition');
      else if (this.pseudorandom('wheel_of_fortune') < 1 / 4) {
        const j = el[this.pickIndex(el.length, this.pseudoseed('wheel_of_fortune')) - 1];
        j.edition = this.pollEdition('wheel_of_fortune', 1, true, true);
        out.text = `Hit: ${j.name} becomes ${j.edition}`; out.jokers.push(j); r = out;
      } else r = Object.assign(out, {text: 'Nope! (no edition this time)'});
    } else if (k === 'c_hex' || k === 'c_ectoplasm') {
      const el = editionless();
      if (!el.length) r = fail('Needs a joker without an edition');
      else {
        const j = el[this.pickIndex(el.length, this.pseudoseed(k === 'c_hex' ? 'hex' : 'ectoplasm')) - 1];
        if (k === 'c_hex') {
          j.edition = 'polychrome';
          const gone = this.jokers.filter(x => x !== j); gone.forEach(x => this._destroyJoker(x));
          out.text = `${j.name} becomes Polychrome` + (gone.length ? `; destroys ${gone.map(x => x.name).join(', ')}` : '');
        } else { j.edition = 'negative'; out.text = `${j.name} becomes Negative; hand size -1`; }
        out.jokers.push(j); r = out;
      }
    } else if (k === 'c_ankh') {
      if (!this.jokers.length) r = fail('Needs a joker to copy');
      else if (this._free() <= 0) r = fail('Needs a free joker slot');
      else {
        const j = this.jokers[this.pickIndex(this.jokers.length, this.pseudoseed('ankh_choice')) - 1];
        const gone = this.jokers.filter(x => x !== j); gone.forEach(x => this._destroyJoker(x));
        const copy = {type: 'Joker', key: j.key, name: j.name, id: id + '.j'};
        if (j.edition && j.edition !== 'negative') copy.edition = j.edition;
        this._gainJoker(copy); out.jokers.push(copy);
        out.text = `Copies ${j.name}` + (gone.length ? `; destroys ${gone.map(x => x.name).join(', ')}` : ''); r = out;
      }
    } else if (k === 'c_soul') {
      if (this._free() <= 0) r = fail('No free joker slot for the legendary');
      else { const L = this.useSoul(); L.id = id + '.leg'; out.jokers.push(L); out.text = `Gives ${L.name}${L.edition ? ' (' + L.edition + ')' : ''}`; c.soul_gives = L; r = out; }
    } else if (k === 'c_black_hole') r = Object.assign(out, {text: 'Every poker hand gains 1 level'});
    else if (cen.s === 'Planet') r = Object.assign(out, {text: `${cen.h} gains 1 level`});
    else if (k === 'c_hermit') r = Object.assign(out, {text: 'Doubles your money (up to +$20)'});
    else if (k === 'c_temperance') r = Object.assign(out, {text: 'Gives the sell value of your jokers (up to $50)'});
    else if (k === 'c_familiar' || k === 'c_grim' || k === 'c_incantation') r = Object.assign(out, {text: 'Destroys 1 random card in hand and adds new enhanced cards (your hand is not simulated)'});
    else if (k === 'c_immolate') r = Object.assign(out, {text: 'Destroys 5 random cards in hand, +$20 (your hand is not simulated)'});
    else if (k === 'c_sigil' || k === 'c_ouija') r = Object.assign(out, {text: 'Changes the cards in your hand (your hand is not simulated)'});
    else r = Object.assign(out, {text: 'Applies to the cards you select in hand (your hand is not simulated)'});
    if (!r.fail) {
      if ((cen.s === 'Tarot' && k !== 'c_fool') || cen.s === 'Planet') this.last_tp = k;
      this._removed(k);
    } else if (ci >= 0) this.cons.splice(ci, 0, c);
    return r;
  }
  _holdConsumable(c) {
    if (c.type !== 'Tarot' && c.type !== 'Planet' && c.type !== 'Spectral') return this._takeCard(c);
    if (this._consFree() <= 0) { c.note = 'No free consumable slot'; return false; }
    c.taken = true; c.held = true;
    this.cons.push({type: c.type, key: c.key, name: c.name, id: c.id, edition: c.edition || null});
    this._created(c.key);
    return true;
  }
  _applyUses(sid) {
    const ids = this.cons.filter(c => this.uses[c.id] === sid).map(c => c.id), used = [];
    for (const id of ids) {
      const c = this.cons.find(x => x.id === id);
      if (!c) continue;
      const r = this.useConsumable(c);
      used.push({key: c.key, name: c.name, edition: c.edition || null, result: r});
    }
    return used;
  }
  _applySells(sid) {
    const sold = [];
    for (let i = this.jokers.length - 1; i >= 0; i--) {
      const j = this.jokers[i];
      if (this.sells[j.id] !== sid) continue;
      this.jokers.splice(i, 1); this._removed(j.key);
      const entry = {key: j.key, name: j.name, edition: j.edition || null, text: null, assumed: false, jokers: [], tags: []};
      this._sellEffect(j, entry);
      sold.push(entry);
    }
    return sold.reverse();
  }
  _sellEffect(j, entry) {
    if (j.key === 'j_diet_cola') {
      this.tags.push('tag_double');
      entry.text = 'Creates a free Double Tag (it copies the next skip tag you take).';
    } else if (j.key === 'j_invisible') {
      // Duplicate a random Joker you own; the copy loses Negative. RNG key not in the provided source -> reconstructed.
      if (!this.jokers.length) { entry.text = 'No other joker to duplicate.'; return; }
      if (this._free() <= 0) { entry.text = 'No free joker slot for the duplicate.'; return; }
      const pick = this.jokers[this.pickIndex(this.jokers.length, this.pseudoseed('invisible')) - 1];
      const copy = {type: 'Joker', key: pick.key, name: pick.name};
      if (pick.edition && pick.edition !== 'negative') copy.edition = pick.edition;
      this._gainJoker(copy);
      entry.jokers.push({key: copy.key, name: copy.name, edition: copy.edition || null, rarity: (C[copy.key] || {}).r});
      entry.text = `Duplicates ${pick.name} (a random one of your jokers; the copy loses Negative).`;
      entry.assumed = true;
    } else if (SELL_EFFECT[j.key]) {
      entry.text = SELL_EFFECT[j.key];
    }
  }
  _perkeo(sid) {
    const own = this.jokers.filter(j => j.key === 'j_perkeo').length;
    if (!own) return [];
    const n = this.perkeo_n !== null ? this.perkeo_n : own, made = [];
    for (let i = 0; i < n; i++) {
      if (!this.cons.length) break;
      const src = this.cons[this.pickIndex(this.cons.length, this.pseudoseed('perkeo')) - 1];
      const nc = {type: src.type, key: src.key, name: src.name, edition: 'negative', id: `${sid}.perkeo${i}`};
      this._created(nc.key); made.push(nc); this._gainCons(nc);
    }
    return made;
  }
  _inv() {
    return {jokers: this.jokers.map(j => ({key: j.key, name: j.name, edition: j.edition || null, rarity: (C[j.key] || {}).r, id: j.id})),
            cons: this.cons.map(c => ({key: c.key, name: c.name, type: c.type, edition: c.edition || null, id: c.id})),
            slots: this.joker_slots + this.jokers.filter(j => j.edition === 'negative').length,
            cslots: 2 + this.cons.filter(c => c.edition === 'negative').length};
  }
  _warn(w) { if (!this.warnings.includes(w)) this.warnings.push(w); }
  addTag(t, events) {
    let copies = 0;
    if (t !== 'tag_double') for (let i = this.tags.length - 1; i >= 0; i--) if (this.tags[i] === 'tag_double') { this.tags.splice(i, 1); copies++; }
    this.tags.push(t);
    for (let i = 0; i < copies; i++) { this.tags.push(t); events.push({event: 'double', tag: t}); }
  }
  blindSelect(events) {
    let i = 0;
    while (i < this.tags.length) {
      const t = this.tags[i];
      if (TAG_TYPE[t] === 'immediate') {
        this.tags.splice(i, 1);
        const ev = {event: 'tag', tag: t};
        if (t === 'tag_top_up') {
          const made = [];
          for (let k = 0; k < 2; k++) if (this._free() > 0) { const c = this.createCard('Joker', 'jokers', false, 0, false, null, 'top'); this._gainJoker(c); made.push(c); }
          ev.cards = made;
        }
        events.push(ev);
        continue;
      }
      i++;
    }
    for (let i2 = 0; i2 < this.tags.length; i2++) {
      const t = this.tags[i2];
      if (TAG_TYPE[t] === 'new_blind_choice') {
        this.tags.splice(i2, 1);
        if (t === 'tag_boss') { const b = this.newBoss(); this.cur_boss = b; events.push({event: 'tag', tag: t, boss: b}); }
        else {
          const booster = Object.assign({key: PACK_TAGS[t]}, C[PACK_TAGS[t]]);
          const ev = {event: 'tag_pack', tag: t, pack: booster};
          if (this.skip_packs.has('tagpack:' + t)) ev.opened = false;
          else { const cards = this.openPack(booster); const tn = this.tagPackN++; cards.forEach((c, i) => c.id = `${this.ctx}.t${tn}.${i}`); this.closePack(booster, cards); ev.opened = true; ev.cards = cards; }
          events.push(ev);
        }
        break;
      }
    }
  }
  shop(sid, g) {
    const S = {id: sid, game_ante: g, rng_ante: this.ante, label: SHOP_LABEL[sid.slice(-1)]};
    this.shop_cards = [];
    if (!(this.fast && this.fast.soulOnly)) for (let i = 0; i < this.joker_max; i++) this.shop_cards.push(this.shopSlot());
    this.curSid = sid; this.pairIdx = 0; this._idSlots();
    S.slots = [this.shop_cards.slice()];
    const vouchers = [];
    if (this.cur_voucher) { vouchers.push(this.cur_voucher); this._created(this.cur_voucher); }
    this.shop_voucher_keys = new Set(vouchers);
    const packs = [this.getPack(), this.getPack()];
    for (const p of packs) this._created(p.key);
    let i = 0;
    while (i < this.tags.length) {
      if (TAG_TYPE[this.tags[i]] === 'voucher_add') {
        this.tags.splice(i, 1);
        const v = this.nextVoucher(true);
        vouchers.push(v); this.shop_voucher_keys.add(v); this._created(v);
        continue;
      }
      i++;
    }
    S.vouchers = vouchers.slice();
    const bought = [];
    for (const v of vouchers) {
      if (this.buy_vouchers.has(v) && !this.used_vouchers.has(v)) {
        bought.push(v);
        if (v === this.cur_voucher) this.cur_voucher = null;
        const before = this.shop_cards.length;
        this.redeemVoucher(v, true);
        if (this.shop_cards.length > before) S.slots[S.slots.length - 1] = this.shop_cards.slice();
      }
    }
    S.bought_vouchers = bought;
    this._idSlots();
    this._takeFromSlots();
    const soulOnly = !!(this.fast && this.fast.soulOnly);
    const doPreview = () => {
      if (!this.preview_rerolls || soulOnly) return;
      const snap = this._snapshot(); const prev = [];
      for (let k = 0; k < this.preview_rerolls; k++) prev.push(this._reroll());
      this._restore(snap);
      S.preview = prev;
    };
    if (!this.interactive) doPreview();            // search path: preview from the start of the shop (unchanged)
    if (!soulOnly) for (let k = 0; k < (this.rerolls[sid] || 0); k++) S.slots.push(this._reroll());
    S.packs = packs.map(p => ({pack: p, opened: false, done: false}));
    S.steps = []; S.used = []; S.sold = [];
    const openPack = (j, auto) => {
      const P = S.packs[j], p = P.pack;
      const cards = this.openPack(p); cards.forEach((c, i) => c.id = `${sid}.p${j + 1}.${i}`); this.closePack(p, cards);
      P.opened = true; P.done = true; P.cards = cards; P.auto = auto;
      this._removed(p.key);
      return cards;
    };
    if (this.interactive) {
      /* the analyzer replays your actions in the exact order you made them: the RNG streams advance in that order */
      const ctx = {S, vouchers, bought, openPack, soulOnly};
      for (const a of (this.plan[sid] || [])) { const st = this._act(a, ctx); if (st) { st.inv = this._inv(); S.steps.push(st); } }
      doPreview();
    }
    S.packs.forEach((P, j) => {                    // packs you did not open explicitly: opened last, in order, unless left closed
      if (P.done) return;
      if (this.skip_packs.has(sid + '.' + (j + 1))) { P.opened = false; P.done = true; this._removed(P.pack.key); return; }
      openPack(j, true);
      if (this.interactive) S.steps.push({t: 'pack', idx: j + 1, auto: true, id: `${sid}.${j + 1}`, pack: P.pack, cards: P.cards, inv: this._inv()});
    });
    if (this.interactive) { S.used = S.used.concat(this._applyUses(sid)); S.sold = S.sold.concat(this._applySells(sid)); S.perkeo = this._perkeo(sid); }
    for (const c of this.shop_cards) if (c && !c.taken) this._removed(c.key);
    for (const v of vouchers) this._removed(v);
    this.shop_cards = null;
    this.shop_voucher_keys = new Set();
    return S;
  }
  /* one user action inside a shop; returns the step record shown in the timeline */
  _act(a, x) {
    const S = x.S, st = {t: a.t};
    if (a.t === 'reroll') {
      if (x.soulOnly) return null;
      st.cards = this._reroll(); S.slots.push(st.cards); st.n = S.slots.length - 1;
    } else if (a.t === 'voucher') {
      st.key = a.key;
      if (!x.vouchers.includes(a.key)) { st.ok = false; st.note = 'This voucher is not in the shop at this point.'; }
      else if (this.used_vouchers.has(a.key)) { st.ok = false; st.note = 'You already own this voucher.'; }
      else {
        x.bought.push(a.key); S.bought_vouchers = x.bought.slice();
        if (a.key === this.cur_voucher) this.cur_voucher = null;
        const before = this.shop_cards.length;
        this.redeemVoucher(a.key, true);
        if (this.shop_cards.length > before) { this._idSlots(); S.slots[S.slots.length - 1] = this.shop_cards.slice(); this._takeFromSlots(); st.extra = this.shop_cards.slice(before); }
        st.ok = true;
      }
    } else if (a.t === 'pack') {
      const j = (a.n | 0) - 1, P = S.packs[j];
      st.idx = j + 1; st.id = `${S.id}.${j + 1}`;
      if (!P) { st.ok = false; st.note = 'This shop has no such pack.'; return st; }
      if (P.done) { st.ok = false; st.note = 'This pack was already opened.'; st.pack = P.pack; }
      else { st.pack = P.pack; st.cards = x.openPack(j, false); st.ok = true; }
    } else if (a.t === 'buy') {
      st.id = a.id;
      const c = this.shop_cards.find(z => z && z.id === a.id);
      if (!c) { st.ok = false; st.note = 'That card is not in the shop at this point (it was rerolled away, or this step is before it appeared).'; }
      else if (c.taken) { st.ok = false; st.note = 'Already taken.'; st.card = c; }
      else { st.card = c; st.hold = !!a.hold; st.ok = a.hold ? this._holdConsumable(c) : this._takeCard(c); if (!st.ok && c.note) st.note = c.note; }
    } else if (a.t === 'use') {
      st.id = a.id;
      const c = this.cons.find(z => z.id === a.id);
      if (!c) { st.ok = false; st.note = 'You are not holding this consumable at this point.'; }
      else { const r = this.useConsumable(c); st.name = c.name; st.edition = c.edition || null; st.key = c.key; st.result = r; st.ok = !r.fail; S.used.push({key: c.key, name: c.name, edition: c.edition || null, result: r}); }
    } else if (a.t === 'sell') {
      st.id = a.id;
      const i = this.jokers.findIndex(z => z.id === a.id);
      if (i < 0) { st.ok = false; st.note = 'You do not own this joker at this point.'; }
      else {
        const j = this.jokers[i]; this.jokers.splice(i, 1); this._removed(j.key);
        const entry = {key: j.key, name: j.name, edition: j.edition || null, text: null, assumed: false, jokers: [], tags: []};
        this._sellEffect(j, entry); S.sold.push(entry); st.entry = entry; st.name = j.name; st.ok = true;
      }
    } else return null;
    return st;
  }
  _idSlots() { this.shop_cards.forEach((c, i) => { if (c && !c.id) c.id = `${this.curSid}.s${this.pairIdx}.${i}`; }); }
  _takeFromSlots() {
    for (const c of this.shop_cards) {
      if (!c || c.taken) continue;
      if (this.interactive && this.picks[c.id] !== undefined) {
        if (this.picks[c.id] === 'hold') this._holdConsumable(c);
        else if (this.picks[c.id] === true) this._takeCard(c);
        continue;
      }
      if (this.take.has(c.key)) {
        if (c.type === 'Joker') { if (this._free() <= 0 && c.edition !== 'negative') continue; this._gainJoker(c); }
        c.taken = true; c.auto = 'take';
      }
    }
  }
  _reroll() {
    for (const c of this.shop_cards) if (c && !c.taken) this._removed(c.key);
    this.shop_cards = []; for (let i = 0; i < this.joker_max; i++) this.shop_cards.push(this.shopSlot());
    this.pairIdx++; this._idSlots();
    this._takeFromSlots();
    return this.shop_cards.slice();
  }
  _snapshot() {
    const keys = ['streams', 'ante', 'used', 'jokers', 'consumables', 'used_vouchers', 'tags', 'bosses_used', 'joker_rate', 'tarot_rate',
      'planet_rate', 'playing_card_rate', 'spectral_rate', 'edition_rate', 'joker_max', 'first_shop_buffoon', 'shop_voucher_keys',
      'shop_cards', 'warnings', 'cur_voucher', 'cur_boss', 'cons', 'last_tp', 'pairIdx'];
    const o = {}; for (const k of keys) o[k] = this[k];
    return [deepClone(o), this.rng.h.slice(), this.rng.l.slice()];
  }
  _restore([o, h, l]) { Object.assign(this, o); this.rng.h = h; this.rng.l = l; }
  /* whole run; onAnte(A) may return false to stop early */
  simulate(antes, onAnte) {
    const out = [];
    this.ante = 1;
    this.cur_boss = this.newBoss();
    this.cur_voucher = this.nextVoucher(false);
    let tags = [this.nextTag(), this.nextTag()];
    this.blindSelect([]);
    for (let g = 1; g <= antes; g++) {
      const A = {ante: g, boss: this.cur_boss, tags: tags.slice(), rounds: []};
      for (const [kind, ti] of [['s', 0], ['b', 1]]) {
        const bid = g + kind;
        this.ctx = bid; this.tagPackN = 0;
        if (this.skips.has(bid)) {
          const ev = []; this.addTag(tags[ti], ev); this.blindSelect(ev);
          A.rounds.push({blind: kind, skipped: true, tag: tags[ti], events: ev, inv: this.interactive ? this._inv() : null});
        } else {
          const S = this.shop(bid, g); const ev = []; this.blindSelect(ev);
          A.rounds.push({blind: kind, skipped: false, shop: S, events: ev, inv: this.interactive ? this._inv() : null});
        }
      }
      A.boss = this.cur_boss;
      this.ante = g + 1;
      this.cur_voucher = this.nextVoucher(false);
      tags = [this.nextTag(), this.nextTag()];
      this.ctx = g + 'x'; this.tagPackN = 0;
      const S = this.shop(g + 'x', g);
      this.cur_boss = this.newBoss();
      const ev = []; this.blindSelect(ev);
      A.rounds.push({blind: 'x', skipped: false, shop: S, events: ev, inv: this.interactive ? this._inv() : null});
      out.push(A);
      if (onAnte && onAnte(A) === false) break;
    }
    return out;
  }
}

function firstLegendary(seed) {
  seed = seed.toUpperCase();
  const pool = DATA.rarity['4'];
  let ps = pseudohash('Joker4' + seed);
  ps = stepState(ps);
  ps = (ps + pseudohash(seed)) / 2;
  const r = new LuaRandom(); r.seed(ps);
  return C[pool[r.randint(pool.length) - 1]].n;
}

/* ------------------------------------------------------------------ events (bridge.events) + criteria */
const ITEM_KEYS = Object.keys(C).sort().concat(Object.keys(DATA.tags).sort(), Object.keys(DATA.blinds).sort());
const IDX = {}; ITEM_KEYS.forEach((k, i) => IDX[k] = i);
const CARD_IDX = {}; DATA.card_keys.forEach((k, i) => CARD_IDX[k] = i);
const ED = {foil: 1, holo: 2, polychrome: 3, negative: 4};
const SEAL = {red: 1, blue: 2, gold: 3, purple: 4};
const KIND_IDX = {s: 0, b: 1, x: 2};
const RAR_OF = ITEM_KEYS.map(k => (C[k] && C[k].s === 'Joker') ? (C[k].r || 0) : 0);
const RARITY_N = {common: 1, uncommon: 2, rare: 3, legendary: 4};
const KIND_OF = ITEM_KEYS.map(k => { const c = C[k]; return c ? ({Joker: 1, Tarot: 2, Planet: 3, Spectral: 4, Enhanced: 5, Voucher: 6, Booster: 7})[c.s] || 0 : 0; });
const GROUP = (() => { const first = {}; return ITEM_KEYS.map(k => { const c = C[k]; if (c && c.s === 'Booster') { if (!(c.n in first)) first[c.n] = IDX[k]; return first[c.n]; } return IDX[k]; }); })();

function anteEvents(A, out) {
  const g = A.ante;
  const cardEv = (loc, kind, rr, c) => {
    if (!c) { out.push([loc, g, kind, rr, -1, 0, 0, -1]); return; }
    if (c.key === null) return;
    out.push([loc, g, kind, rr, IDX[c.key], ED[c.edition] || 0, SEAL[(c.seal || '').toLowerCase()] || 0, c.card_key ? CARD_IDX[c.card_key] : -1]);
    if (c.soul_gives) out.push([5, g, kind, rr, IDX[c.soul_gives.key], ED[c.soul_gives.edition] || 0, 0, -1]);
  };
  const roundEv = R => {
    for (const e of R.events || []) {
      if (e.event === 'tag' && e.cards) for (const c of e.cards) out.push([7, g, 3, 0, IDX[c.key], ED[c.edition] || 0, 0, -1]);
      else if (e.event === 'tag_pack' && e.opened) for (const c of e.cards) cardEv(1, 3, 0, c);
    }
  };
  const shopEv = S => {
    const k = KIND_IDX[S.id.slice(-1)];
    for (const v of S.vouchers) out.push([2, g, k, 0, IDX[v], 0, 0, -1]);
    for (const P of S.packs) out.push([6, g, k, 0, IDX[P.pack.key], 0, 0, -1]);
    for (const c of S.slots[0]) cardEv(0, k, 0, c);
    (S.preview || []).forEach((pair, i) => { for (const c of pair) cardEv(0, k, i + 1, c); });
    for (const pair of S.slots.slice(1)) for (const c of pair) cardEv(0, k, 0, c);
    for (const P of S.packs) if (P.opened) for (const c of P.cards) cardEv(1, k, 0, c);
  };
  out.push([3, g, 3, 0, IDX[A.tags[0]], 0, 0, -1]);
  out.push([3, g, 3, 0, IDX[A.tags[1]], 0, 0, -1]);
  for (const R of A.rounds) {
    if (R.blind === 'x') out.push([4, g, 3, 0, IDX[A.boss], 0, 0, -1]);
    if (!R.skipped) shopEv(R.shop);
    roundEv(R);
  }
  return out;
}
function events(T) { const out = []; for (const A of T) anteEvents(A, out); return out; }

const LOCS = {shop: 0, pack: 1, voucher: 2, tag: 3, boss: 4, legend: 5, packtype: 6, joker: 7, card: 8};
function resolve(q) {
  const ql = q.trim().toLowerCase();
  for (const [src, keyN] of [[C, 'n'], [DATA.tags, 'n'], [DATA.blinds, 'n']])
    for (const k in src) { const n = (src[k][keyN] || '').toLowerCase(); if (ql === k.toLowerCase() || ql === n || (n.endsWith(' tag') && ql === n.slice(0, -4))) return k; }
  throw new Error(`Unknown item "${q}"`);
}
function parseCrit(spec) {
  const parts = spec.split(':');
  if (parts.length < 2 || !(parts[0].toLowerCase() in LOCS)) throw new Error(`Bad condition "${spec}"`);
  const c = {spec, loc: LOCS[parts[0].toLowerCase()], id: -1, lo: 1, hi: 1, edition: 0, seal: 0, count: 1, shopmask: 0, rerolls: 0, card: -1, enh: -1, rarity: 0};
  const item = parts[1].trim(); const rest = parts.slice(2);
  if (rest.length && !rest[0].includes('=')) { const a = rest.shift(); if (a.includes('-')) { [c.lo, c.hi] = a.split('-').map(Number); } else c.lo = c.hi = +a; }
  const it0 = item.toLowerCase().replace(/^any /, '').replace(/ jokers?$/, '');
  if (RARITY_N[it0] && [0, 1, 5, 7].includes(c.loc)) { c.rarity = RARITY_N[it0]; }
  else if (item.toLowerCase() !== 'any') {
    if (c.loc === 8) { const i = DATA.card_keys.findIndex(k => DATA.cards[k].toLowerCase() === item.toLowerCase()); if (i < 0) throw new Error(`Unknown playing card "${item}"`); c.card = i; }
    else {
      let key = resolve(item);
      if (c.loc === 6) { const nm = C[key].n; key = Object.keys(C).filter(k => C[k].s === 'Booster' && C[k].n === nm).sort((a, b) => IDX[a] - IDX[b])[0]; }
      c.id = IDX[key]; c.key = key;
    }
  }
  for (const r of rest) {
    const [k, v] = r.split('='), kk = k.trim().toLowerCase(), vv = (v || '').trim();
    if (kk === 'edition' || kk === 'ed') { if (!ED[vv.toLowerCase()]) throw new Error('edition must be foil, holo, polychrome or negative'); c.edition = ED[vv.toLowerCase()]; }
    else if (kk === 'seal') { if (!SEAL[vv.toLowerCase()]) throw new Error('seal must be red, blue, gold or purple'); c.seal = SEAL[vv.toLowerCase()]; }
    else if (kk === 'count' || kk === 'n') c.count = +vv;
    else if (kk === 'shop') { let m = 0; for (const x of vv.toLowerCase().replace(/\+/g, ',').split(',')) m |= 1 << ({s: 0, small: 0, b: 1, big: 1, x: 2, boss: 2, tag: 3})[x]; c.shopmask = m; }
    else if (kk === 'rerolls') c.rerolls = +vv;
    else if (kk === 'rarity') { if (!RARITY_N[vv.toLowerCase()]) throw new Error('rarity must be common, uncommon, rare or legendary'); c.rarity = RARITY_N[vv.toLowerCase()]; }
    else if (kk === 'enh' || kk === 'enhancement') c.enh = IDX[resolve(vv)];
    else throw new Error(`Unknown option "${kk}" in "${spec}"`);
  }
  return c;
}
function match(c, e) {
  const [loc, g, kind, rr, iid, ed, seal, card] = e;
  if (g < c.lo || g > c.hi || rr > c.rerolls) return false;
  if (c.shopmask && !((c.shopmask >> kind) & 1)) return false;
  if (c.edition && c.edition !== ed) return false;
  if (c.seal && c.seal !== seal) return false;
  if (c.rarity && (iid < 0 || RAR_OF[iid] !== c.rarity)) return false;
  const idm = c.id < 0 || c.id === iid;
  switch (c.loc) {
    case 0: return loc === 0 && idm;
    case 1: return loc === 1 && idm;
    case 2: return loc === 2 && idm;
    case 3: return loc === 3 && idm;
    case 4: return loc === 4 && idm;
    case 5: return loc === 5 && idm;
    case 6: return loc === 6 && (c.id < 0 || c.id === GROUP[iid]);
    case 7: return (loc === 0 || loc === 1 || loc === 5 || loc === 7) && iid >= 0 && KIND_OF[iid] === 1 && idm;
    case 8: return (loc === 0 || loc === 1) && card >= 0 && (c.card < 0 || c.card === card) && (c.enh < 0 || c.enh === iid);
  }
  return false;
}
/* check one seed; returns null or the list of matching events per criterion */
/* search-only shortcuts, the same conditions as core.h run_init (proven there to give identical hits) */
function fastFlags(opts, crits) {
  const noTake = !(opts.take && opts.take.length);
  let soul = false, lite = noTake, np = noTake, ned = noTake, mods = false;
  for (const c of crits) {
    if ((c.loc === 0 || c.loc === 1 || c.loc === 7 || c.loc === 8) && (c.edition || c.seal)) mods = true;
    if (c.loc === 5) soul = true;
    else if (c.loc === 1 && (c.key === 'c_soul' || c.key === 'c_black_hole') && !c.edition && !c.seal) soul = true;
    else if (c.loc === 0 || c.loc === 1 || c.loc === 7 || c.loc === 8) lite = false;
    if (c.loc === 1 || c.loc === 5 || c.loc === 7 || c.loc === 8) np = false;
    if (c.edition) ned = false;
  }
  return {soulOnly: lite && soul, noPacks: np, noEd: np && ned, mods};
}
function check(seed, opts, crits, fast) {
  const antes = Math.max(...crits.map(c => c.hi));
  const o = Object.assign({}, opts, {preview_rerolls: Math.max(0, ...crits.map(c => c.rerolls))});
  const run = new Run(seed, o);
  if (fast !== false) run.fast = fastFlags(opts, crits);
  const cnt = crits.map(() => 0), where = crits.map(() => []);
  let failed = false;
  run.simulate(antes, A => {
    const evs = anteEvents(A, []);
    for (const e of evs) crits.forEach((c, i) => { if (match(c, e)) { cnt[i]++; where[i].push(e); } });
    for (let i = 0; i < crits.length; i++) if (crits[i].hi <= A.ante && cnt[i] < crits[i].count) { failed = true; return false; }
    return true;
  });
  if (failed) return null;
  for (let i = 0; i < crits.length; i++) if (cnt[i] < crits[i].count) return null;
  return where;
}
const NAMES = ITEM_KEYS.map(k => (C[k] || DATA.tags[k] || DATA.blinds[k]).n);
const CARD_NAMES = DATA.card_keys.map(k => DATA.cards[k]);
const KIND_TXT = ['after Small Blind', 'after Big Blind', 'after Boss Blind', 'from a tag'];
function describe(where, c, limit) {
  limit = limit || 4;
  const out = [];
  for (const [loc, g, kind, rr, iid, ed, seal, card] of where.slice(0, limit)) {
    let nm = iid >= 0 ? NAMES[iid] : '?';
    if (card >= 0) nm = CARD_NAMES[card] + (NAMES[iid] === 'Default Base' ? '' : ' ' + NAMES[iid]);
    const t = [];
    if (ed) t.push(['', 'Foil', 'Holo', 'Polychrome', 'Negative'][ed]);
    if (seal) t.push(['', 'Red', 'Blue', 'Gold', 'Purple'][seal] + ' Seal');
    if (t.length) nm += ' (' + t.join(', ') + ')';
    const sh = kind !== 3 ? KIND_TXT[kind] : '';
    let place;
    if (loc === 0) place = `shop slot, ante ${g} ${sh}` + (rr ? `, after ${rr} reroll${rr > 1 ? 's' : ''}` : '');
    else if (loc === 1) place = kind !== 3 ? `pack, ante ${g} ${sh}` : `pack from a skip tag, ante ${g}`;
    else if (loc === 5) place = kind !== 3 ? `from The Soul, ante ${g} ${sh}` : `from The Soul in a tag pack, ante ${g}`;
    else if (loc === 7) place = `Top-up Tag, ante ${g}`;
    else if (loc === 2) place = `voucher, ante ${g} ${sh}`;
    else if (loc === 6) place = `booster in shop, ante ${g} ${sh}`;
    else if (loc === 3) place = `skip tag, ante ${g}`;
    else place = `boss, ante ${g}`;
    out.push(`${nm} [${place.trim()}]`);
  }
  if (where.length > limit) out.push(`+${where.length - limit} more`);
  return out.join('; ');
}

/* ------------------------------------------------------------------ seed space (shortlex, as searcher.py) */
function spaceSize(a, b) { let n = 0; for (let L = a; L <= b; L++) n += 34 ** L; return n; }
function idx2seed(n, a, b) {
  let L = a;
  while (L < b && n >= 34 ** L) { n -= 34 ** L; L++; }
  let s = '';
  for (let i = 0; i < L; i++) { s = SEED_CHARS[n % 34] + s; n = Math.floor(n / 34); }
  return s;
}
function seed2idx(s, a, b) {
  s = s.toUpperCase();
  if (s.length < a || s.length > b) throw new Error(`Seed "${s}" is not ${a}-${b} characters long`);
  let n = 0; for (let L = a; L < s.length; L++) n += 34 ** L;
  let v = 0; for (const ch of s) v = v * 34 + SEED_CHARS.indexOf(ch);
  return n + v;
}
const validSeed = s => /^[1-9A-NP-Z]{1,8}$/.test(s);

/* ------------------------------------------------------------------ view model for the UI (same shape as app.py) */
function resultVM(r) { return {text: r.text, fail: !!r.fail, created: (r.created || []).map(cardVM), jokers: (r.jokers || []).map(cardVM)}; }
function cardVM(c) {
  if (!c) return null;
  const k = c.key, cen = C[k] || {}, t = c.type, vm = {key: k, name: c.name};
  if (k === 'c_soul') vm.kind = 'soul';
  else if (k === 'c_black_hole') vm.kind = 'blackhole';
  else if (t === 'Joker') { vm.kind = 'joker'; vm.rarity = cen.r; }
  else if (t === 'Base' || t === 'Enhanced') { vm.kind = 'card'; vm.name = c.card || c.name; if (k !== 'c_base') vm.enh = c.name; }
  else vm.kind = t.toLowerCase();
  for (const f of ['edition', 'seal', 'sticker', 'rental', 'taken', 'from_tag', 'id', 'note', 'used', 'held', 'created', 'auto']) if (c[f]) vm[f] = c[f];
  if (c.soul_gives) vm.legendary = {key: c.soul_gives.key, name: c.soul_gives.name, edition: c.soul_gives.edition || null};
  if (c.result) vm.result = resultVM(c.result);
  return vm;
}
function stepVM(st) {
  const v = {t: st.t};
  for (const f of ['n', 'ok', 'note', 'idx', 'id', 'auto', 'hold', 'name', 'edition', 'key']) if (st[f] !== undefined && st[f] !== null) v[f] = st[f];
  if (st.t === 'voucher') v.name = (C[st.key] || {}).n;
  if (st.cards) v.cards = st.cards.map(cardVM);
  if (st.extra) v.extra = st.extra.map(cardVM);
  if (st.pack) v.pack = {key: st.pack.key, name: st.pack.n, kind: st.pack.k, choose: st.pack.c || 1, size: st.pack.e};
  if (st.card) v.card = cardVM(st.card);
  if (st.result) v.result = resultVM(st.result);
  if (st.entry) v.entry = st.entry;
  if (st.inv) v.inv = st.inv;
  return v;
}
function analyze(seed, antes, preview, opts) {
  seed = seed.toUpperCase();
  if (!validSeed(seed)) throw new Error('A seed is 1 to 8 characters from 1-9, A-N and P-Z (no 0 or O).');
  const run = new Run(seed, Object.assign({}, opts, {preview_rerolls: preview || 0}));
  let lastInv = null;
  const T = run.simulate(antes);
  const legs = [], antesVM = [];
  for (const A of T) {
    const g = A.ante, rounds = [];
    for (const R of A.rounds) {
      const rv = {blind: R.blind, skipped: !!R.skipped};
      if (R.inv) { rv.inv = R.inv; lastInv = R.inv; }
      if (R.skipped) rv.tag = {key: R.tag, name: DATA.tags[R.tag].n};
      else {
        const S = R.shop;
        rv.shop = {id: S.id, rng_ante: S.rng_ante,
          vouchers: S.vouchers.map(v => ({key: v, name: C[v].n, bought: S.bought_vouchers.includes(v)})),
          slots: S.slots.map(p => p.map(cardVM)), preview: (S.preview || []).map(p => p.map(cardVM)),
          perkeo: (S.perkeo || []).map(cardVM), sold: (S.sold || []), used: (S.used || []).map(u => ({key: u.key, name: u.name, edition: u.edition, result: resultVM(u.result)})),
          steps: (S.steps || []).map(stepVM),
          packs: S.packs.map((P, j) => ({key: P.pack.key, name: P.pack.n, kind: P.pack.k, choose: P.pack.c || 1, size: P.pack.e, opened: P.opened, auto: !!P.auto,
            id: `${S.id}.${j + 1}`, cards: (P.cards || []).map(cardVM)}))};
        for (const P of rv.shop.packs) for (const c of P.cards) if (c && c.legendary) legs.push(Object.assign({ante: g, where: 'shop ' + SHOP_LABEL[R.blind], pack: P.name}, c.legendary));
      }
      rv.events = (R.events || []).map(e => {
        const ev = {event: e.event, tag: {key: e.tag, name: DATA.tags[e.tag].n}};
        if (e.boss) ev.boss = {key: e.boss, name: DATA.blinds[e.boss].n};
        if (e.event === 'tag_pack') { ev.pack = {key: e.pack.key, name: e.pack.n, kind: e.pack.k}; ev.opened = !!e.opened; }
        if (e.cards) { ev.cards = e.cards.map(cardVM); for (const c of ev.cards) if (c && c.legendary) legs.push(Object.assign({ante: g, where: ev.tag.name, pack: ev.pack ? ev.pack.name : ''}, c.legendary)); }
        return ev;
      });
      rounds.push(rv);
    }
    antesVM.push({ante: g, boss: {key: A.boss, name: DATA.blinds[A.boss].n}, tags: A.tags.map(t => ({key: t, name: DATA.tags[t].n})), rounds});
  }
  const out = {seed, deck: C[run.deck].n, stake: STAKES[run.stake - 1], first_legendary: firstLegendary(seed), legendaries: legs, antes: antesVM, warnings: run.warnings};
  if (lastInv) out.inventory = lastInv;
  return out;
}

function meta() {
  const list = (set, extra) => Object.keys(C).filter(k => C[k].s === set).map(k => Object.assign({key: k, name: C[k].n}, extra ? extra(C[k]) : {})).sort((a, b) => a.name.localeCompare(b.name));
  const seen = new Set(), packs = [];
  for (const b of BOOSTERS) if (!seen.has(b.n)) { seen.add(b.n); packs.push({key: b.key, name: b.n, kind: b.k}); }
  return {
    decks: Object.keys(C).filter(k => C[k].s === 'Back' && k !== 'b_challenge').sort((a, b) => C[a].o - C[b].o).map(k => ({key: k, name: C[k].n})),
    stakes: STAKES, jokers: list('Joker', c => ({rarity: c.r})), tarots: list('Tarot'), planets: list('Planet'), spectrals: list('Spectral'),
    vouchers: list('Voucher', c => ({requires: c.rq ? c.rq[0] : null})), enhancements: list('Enhanced'),
    tags: Object.keys(DATA.tags).map(k => ({key: k, name: DATA.tags[k].n})).sort((a, b) => a.name.localeCompare(b.name)),
    bosses: BOSS_KEYS.map(k => ({key: k, name: DATA.blinds[k].n, showdown: !!DATA.blinds[k].b[2]})).sort((a, b) => a.name.localeCompare(b.name)),
    packs, hands: Object.keys(PLANET_BY_HAND).sort(), cards: CARD_NAMES.slice()};
}

/* ------------------------------------------------------------------ where can a card show up in this seed?
   Every result is produced by simulating that exact path (rerolls / using a card / skipping a blind). */
function locate(seed, opts, key, antes, maxRr, wantEd) {
  seed = seed.toUpperCase();
  wantEd = wantEd || null;
  const KIND = {s: 'Small', b: 'Big', x: 'Boss'};
  const shopName = sid => `shop after ${KIND[sid.slice(-1)]} Blind`;
  const out = [], seen = new Set();
  const add = a => {
    if (wantEd && a.edition !== wantEd) return;
    a.name = a.name || ((C[a.key] || {}).n);
    const k = a.how + '|' + a.where + '|' + a.key + '|' + (a.edition || '');
    if (!seen.has(k)) { seen.add(k); out.push(a); }
  };
  const base = new Run(seed, Object.assign({}, opts, {interactive: true, preview_rerolls: maxRr}));
  const T = base.simulate(antes);
  const rar = /^rarity:(\d)$/.exec(key) ? +key.slice(7) : 0;
  const targetSet = rar ? 'Joker' : (C[key] || {}).s;
  const hitKey = k => rar ? ((C[k] || {}).s === 'Joker' && (C[k] || {}).r === rar) : k === key;
  const isTarget = c => c && c.key && hitKey(c.key);
  const users = [];                                   // Judgement / Wraith / Soul cards that could create it
  const creators = new Set(['c_judgement', 'c_wraith', 'c_soul']);
  const tr = rar || (C[key] || {}).r || 0, isJoker = rar || targetSet === 'Joker';
  const canCreate = k => (k === 'c_judgement' && isJoker && tr !== 4) || (k === 'c_wraith' && tr === 3) || (k === 'c_soul' && tr === 4);
  const scanCards = (cards, g, where, how, extra) => (cards || []).forEach(c => {
    if (!c) return;
    if (isTarget(c)) add(Object.assign({ante: g, where, how, key: c.key, edition: c.edition || null, id: c.id, taken: !!c.taken}, extra || {}));
    if (c.soul_gives && hitKey(c.soul_gives.key)) add(Object.assign({ante: g, where: where + ', from The Soul', how, key: c.soul_gives.key, edition: c.soul_gives.edition || null, id: c.id, taken: true}, extra || {}));
    if (c.result) for (const j of c.result.jokers || []) if (hitKey(j.key)) add(Object.assign({ante: g, where: where + `, created by ${c.name}`, how, key: j.key, edition: j.edition || null, id: c.id, taken: true}, extra || {}));
    if (creators.has(c.key) && canCreate(c.key) && !c.taken && !c.used && c.id) users.push(Object.assign({card: c, ante: g, where}, extra || {}));
  });
  for (const A of T) for (const R of A.rounds) {
    const g = A.ante;
    if (R.shop) {
      const S = R.shop, sn = shopName(S.id);
      S.slots.forEach((pair, i) => scanCards(pair, g, `${sn}, shop card` + (i ? ` after your reroll ${i}` : ''), i ? 'your rerolls' : 'direct', {sid: S.id}));
      (S.preview || []).forEach((pair, i) => scanCards(pair, g, `${sn}, after ${i + 1} reroll${i ? 's' : ''}`, 'reroll', {sid: S.id, rerolls: i + 1}));
      S.packs.forEach((P, j) => { if (P.opened) scanCards(P.cards, g, `${sn}, ${P.pack.n} (pack ${j + 1})`, 'direct', {sid: S.id}); });
      if (targetSet === 'Voucher') for (const v of S.vouchers || []) if (hitKey(v)) add({ante: g, where: `${sn}, voucher`, how: 'direct', key: v, edition: null});
    }
    for (const e of R.events || []) if (e.cards) scanCards(e.cards, g, e.event === 'tag_pack' ? `${DATA.tags[e.tag].n} pack` : DATA.tags[e.tag].n, 'direct');
  }
  // use a Judgement / Wraith / Soul where it appears (jokers only)
  for (const u of users.slice(0, 40)) {
    const o = deepClone(Object.assign({}, opts)); o.picks = Object.assign({}, opts.picks || {}, {[u.card.id]: true});
    if (u.rerolls) { o.plan = deepClone(opts.plan || {}); o.plan[u.sid] = (o.plan[u.sid] || []).concat(Array.from({length: u.rerolls}, () => ({t: 'reroll'}))); }
    const r = new Run(seed, Object.assign({}, o, {interactive: true}));
    let hit = null;
    r.simulate(u.ante, A => {
      for (const R of A.rounds) {
        const all = [];
        if (R.shop) { R.shop.slots.forEach(p => all.push(...p)); R.shop.packs.forEach(P => all.push(...(P.cards || []))); }
        (R.events || []).forEach(e => all.push(...(e.cards || [])));
        for (const c of all) if (c && c.id === u.card.id) hit = c;
      }
    });
    if (!hit) continue;
    const made = (hit.result && hit.result.jokers || []).concat(hit.soul_gives ? [hit.soul_gives] : []);
    for (const j of made) if (hitKey(j.key))
      add({ante: u.ante, where: `${u.where}: use ${u.card.name}`, how: 'use', key: j.key, edition: j.edition || null, id: u.card.id, sid: u.sid, rerolls: u.rerolls, pick: u.card.id});
  }
  // skip a blind for a tag that brings the target
  const skipTags = {Joker: ['tag_buffoon', 'tag_uncommon', 'tag_rare', 'tag_top_up'], Tarot: ['tag_charm'],
    Planet: ['tag_meteor'], Spectral: ['tag_ethereal'], Enhanced: ['tag_standard'], Base: ['tag_standard'],
    Voucher: ['tag_voucher']}[targetSet] || [];
  for (const A of T) for (const [kind, ti] of [['s', 0], ['b', 1]]) {
    const bid = A.ante + kind, t = A.tags[ti];
    if ((opts.skips || []).includes(bid) || !skipTags.includes(t)) continue;
    const o = Object.assign({}, opts, {skips: (opts.skips || []).concat([bid]), interactive: true});
    const r = new Run(seed, o);
    const Tv = r.simulate(Math.min(antes, A.ante + 1));
    const pre = `skip the ${KIND[kind]} Blind of ante ${A.ante} for the ${DATA.tags[t].n}`;
    for (const B of Tv) for (const R of B.rounds) {
      for (const e of R.events || []) if (e.tag === t) for (const c of e.cards || []) if (isTarget(c))
        add({ante: B.ante, where: pre + (e.event === 'tag_pack' ? ` (its ${e.pack.n})` : ''), how: 'skip', key: c.key, edition: c.edition || null, skip: bid, id: c.id});
      if (R.shop) {
        for (const c of R.shop.slots[0]) if (isTarget(c) && c.from_tag)
          add({ante: B.ante, where: `${pre}: first card of the ${shopName(R.shop.id)}`, how: 'skip', key: c.key, edition: c.edition || null, skip: bid, id: c.id});
        if (targetSet === 'Voucher') for (const v of R.shop.vouchers || []) if (hitKey(v))
          add({ante: B.ante, where: `${pre}: extra voucher in the ${shopName(R.shop.id)}`, how: 'skip', key: v, edition: null, skip: bid});
      }
    }
  }
  const order = {direct: 0, 'your rerolls': 0, reroll: 1, use: 2, skip: 3};
  out.sort((a, b) => a.ante - b.ante || order[a.how] - order[b.how] || (a.rerolls || 0) - (b.rerolls || 0));
  return out;
}

/* plain-text / markdown export */
function render(d, md) {
  const L = [], b = s => md ? `**${s}**` : s, bl = {s: 'Small Blind', b: 'Big Blind', x: 'Boss Blind'};
  const ct = c => {
    if (!c) return '(empty)';
    if (c.kind === 'soul') return b('THE SOUL') + (c.legendary ? ' -> ' + b(c.legendary.name + (c.legendary.edition ? ` (${c.legendary.edition})` : '')) : '');
    if (c.kind === 'blackhole') return b('BLACK HOLE');
    let s = c.name + (c.enh ? ` (${c.enh})` : '');
    const x = [c.edition, c.seal && c.seal + ' Seal', c.sticker, c.rental && 'Rental', c.from_tag && 'from ' + c.from_tag].filter(Boolean);
    if (x.length) s += ' [' + x.join(', ') + ']';
    return s + (c.taken ? ' (taken)' : '');
  };
  L.push((md ? '# ' : '') + `Seed ${d.seed} | ${d.deck} | ${d.stake} Stake`);
  L.push(`First legendary (get_first_legendary): ${d.first_legendary}`);
  if (d.legendaries.length) { L.push(''); L.push((md ? '## ' : '') + `Legendaries from The Soul (${d.legendaries.length})`); for (const l of d.legendaries) L.push((md ? '- ' : '  * ') + `${l.name}${l.edition ? ' (' + l.edition + ')' : ''} - ante ${l.ante}, ${l.where}`); }
  for (const A of d.antes) {
    L.push(''); L.push(md ? `## Ante ${A.ante}` : `=================== ANTE ${A.ante} ===================`);
    L.push(`Boss: ${A.boss.name}   |   Skip tags: Small -> ${A.tags[0].name}, Big -> ${A.tags[1].name}`);
    for (const R of A.rounds) {
      L.push('');
      if (R.skipped) { L.push((md ? '### ' : '-- ') + `${bl[R.blind]}: SKIPPED -> ${R.tag.name}`); }
      else {
        const S = R.shop, p = md ? '- ' : '   ';
        L.push((md ? '### ' : '-- ') + `Shop ${SHOP_LABEL[R.blind]}` + (R.blind === 'x' ? ` (rolled with ante ${S.rng_ante})` : ''));
        L.push(p + 'Voucher: ' + (S.vouchers.map(v => v.name + (v.bought ? ' (bought)' : '')).join(', ') || '(none)'));
        S.slots.forEach((pair, i) => L.push(p + (i ? `After reroll ${i}: ` : 'Shop cards: ') + pair.map(ct).join(' | ')));
        S.preview.forEach((pair, i) => L.push(p + `(if you reroll ${i + 1}x): ` + pair.map(ct).join(' | ')));
        if (S.steps && S.steps.length) {
          L.push(p + 'Your actions, in order:');
          const nm = x => x ? x.name : '?';
          S.steps.forEach((st, i) => {
            let t;
            if (st.t === 'reroll') t = `Reroll -> ${st.cards.map(ct).join(' | ')}`;
            else if (st.t === 'voucher') t = `Buy voucher ${st.name}` + (st.ok ? '' : ` (${st.note})`);
            else if (st.t === 'pack') t = `${st.auto ? 'Open (automatic, last) ' : 'Open '}${st.pack.name}: ` + (st.cards || []).map(ct).join(', ');
            else if (st.t === 'buy') t = `${st.hold ? 'Hold' : 'Take'} ${st.card ? nm(st.card) : st.id}` + (st.ok ? '' : ` (${st.note})`) + (st.card && st.card.result ? ' -> ' + st.card.result.text : '');
            else if (st.t === 'use') t = `Use ${st.name || st.id}` + (st.result ? ' -> ' + st.result.text : ` (${st.note})`);
            else if (st.t === 'sell') t = `Sell ${st.name || st.id}` + (st.ok ? '' : ` (${st.note})`);
            L.push(p + `  ${i + 1}. ` + t);
          });
        }
        S.packs.forEach((P, j) => L.push(p + `Pack ${j + 1}: ${P.name} (choose ${P.choose} of ${P.size}): ` + (P.opened ? P.cards.map(ct).join(', ') : 'not opened')));
      }
      for (const e of R.events) {
        let t;
        if (e.event === 'tag_pack') t = `${e.tag.name} opens ${e.pack.name}: ` + (e.opened ? e.cards.map(ct).join(', ') : 'not opened');
        else if (e.event === 'double') t = `Double Tag copies ${e.tag.name}`;
        else if (e.boss) t = `Boss Tag rerolls the boss -> ${e.boss.name}`;
        else if (e.cards) t = `${e.tag.name}: ` + e.cards.map(ct).join(', ');
        else t = `${e.tag.name} used`;
        L.push((md ? '- ' : '   ') + 'Tag: ' + t);
      }
    }
  }
  for (const w of d.warnings) L.push((md ? '> ' : '') + 'Warning: ' + w);
  return L.join('\n');
}

return {Run, LuaRandom, pseudohash, stepState, round13, fastFlags, locate, firstLegendary, events, anteEvents, parseCrit, match, check, describe,
        spaceSize, idx2seed, seed2idx, validSeed, analyze, meta, render, IDX, ITEM_KEYS, SEED_CHARS, STAKES, SHOP_LABEL};
}
if (typeof module !== 'undefined' && module.exports) module.exports = BalatroEngine;
else root.BalatroEngine = BalatroEngine;
})(typeof self !== 'undefined' ? self : this);
