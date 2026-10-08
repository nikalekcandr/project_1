/** Deterministic PRNG (mulberry32) so generated ideas and simulations are reproducible by seed. */
export type Rng = () => number;

export function createRng(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hashString(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function pick<T>(rng: Rng, items: readonly T[]): T {
  if (items.length === 0) throw new Error("pick() from empty list");
  return items[Math.floor(rng() * items.length)];
}

export function shuffle<T>(rng: Rng, items: readonly T[]): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Samples a triangular distribution — the standard choice for "min / most likely / max" expert estimates. */
export function triangular(rng: Rng, min: number, mode: number, max: number): number {
  if (max <= min) return min;
  const m = Math.min(Math.max(mode, min), max);
  const u = rng();
  const c = (m - min) / (max - min);
  return u < c ? min + Math.sqrt(u * (max - min) * (m - min)) : max - Math.sqrt((1 - u) * (max - min) * (max - m));
}

export function newId(prefix = "id"): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `${prefix}_${Date.now().toString(36)}${rand}`;
}
