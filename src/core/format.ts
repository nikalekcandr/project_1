export type CurrencyCode = "RUB" | "USD" | "EUR" | "KZT" | "BYN" | "UAH";

export const CURRENCIES: Record<CurrencyCode, { symbol: string; label: string }> = {
  RUB: { symbol: "₽", label: "Рубль (₽)" },
  USD: { symbol: "$", label: "Доллар США ($)" },
  EUR: { symbol: "€", label: "Евро (€)" },
  KZT: { symbol: "₸", label: "Тенге (₸)" },
  BYN: { symbol: "Br", label: "Белорусский рубль (Br)" },
  UAH: { symbol: "₴", label: "Гривна (₴)" },
};

const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

export function fmtNumber(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return "—";
  return (digits === 0 ? nf0 : digits === 1 ? nf1 : nf2).format(value);
}

/** Compact money: 1 250 000 → "1,25 млн ₽". */
export function fmtMoney(value: number, currency: CurrencyCode = "RUB", compact = true): string {
  if (!Number.isFinite(value)) return "—";
  const symbol = CURRENCIES[currency].symbol;
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (compact) {
    if (abs >= 1e12) return `${sign}${nf2.format(abs / 1e12)} трлн ${symbol}`;
    if (abs >= 1e9) return `${sign}${nf2.format(abs / 1e9)} млрд ${symbol}`;
    if (abs >= 1e6) return `${sign}${nf2.format(abs / 1e6)} млн ${symbol}`;
    if (abs >= 1e4) return `${sign}${nf1.format(abs / 1e3)} тыс. ${symbol}`;
  }
  return `${sign}${nf0.format(abs)} ${symbol}`;
}

export function fmtPercent(value: number, digits = 0): string {
  if (!Number.isFinite(value)) return "—";
  return `${(digits === 0 ? nf0 : digits === 1 ? nf1 : nf2).format(value * 100)}%`;
}

/** `ceil` suits paybacks: 3.4 months of payback means the money is back during month 4. */
export function fmtMonths(value: number | null | undefined, ceil = false): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const n = ceil ? Math.ceil(value - 1e-9) : Math.round(value);
  return `${n} ${plural(n, "месяц", "месяца", "месяцев")}`;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = Math.abs(n) % 10;
  const mod100 = Math.abs(n) % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function round(value: number, digits = 0): number {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

/** Rounds up to a "nice" number for funding asks: 1 234 567 → 1 300 000. */
export function niceCeil(value: number): number {
  if (value <= 0) return 0;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = magnitude / 10 >= 1 ? magnitude / 10 : 1;
  return Math.ceil(value / step) * step;
}

const TRANSLIT: Record<string, string> = {
  а: "a",
  б: "b",
  в: "v",
  г: "g",
  д: "d",
  е: "e",
  ё: "e",
  ж: "zh",
  з: "z",
  и: "i",
  й: "y",
  к: "k",
  л: "l",
  м: "m",
  н: "n",
  о: "o",
  п: "p",
  р: "r",
  с: "s",
  т: "t",
  у: "u",
  ф: "f",
  х: "h",
  ц: "ts",
  ч: "ch",
  ш: "sh",
  щ: "sch",
  ъ: "",
  ы: "y",
  ь: "",
  э: "e",
  ю: "yu",
  я: "ya",
};

/** ASCII file name from any title: "Бизнес-план «Кофе»" → "biznes-plan-kofe" (non-ASCII names break some downloads). */
export function slugify(text: string, fallback = "bizforge"): string {
  const latin = [...text.toLowerCase()].map((ch) => TRANSLIT[ch] ?? ch).join("");
  const slug = latin
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return slug || fallback;
}
