/**
 * Rampe de valeur « magma » (luminance monotone : lisible en niveaux de gris et pour
 * les daltonismes courants) et classes par quantiles des données affichées.
 */
export type Rgb = readonly [number, number, number];

export const RAMP: readonly Rgb[] = [
  [48, 32, 108],
  [96, 42, 140],
  [150, 52, 136],
  [208, 78, 112],
  [240, 128, 84],
  [250, 186, 92],
  [252, 236, 168],
];

export function hex(c: Rgb): string {
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

/** Bornes de classes (n − 1 seuils) par quantiles, arrondies à 10 €/m² comme l'API. */
export function quantileBreaks(values: readonly number[], classes = RAMP.length): number[] {
  if (values.length === 0) return [];
  const sorted = [...values].sort((a, b) => a - b);
  const out: number[] = [];
  for (let i = 1; i < classes; i++) {
    const pos = (sorted.length - 1) * (i / classes);
    const lo = sorted[Math.floor(pos)] ?? 0;
    const hi = sorted[Math.ceil(pos)] ?? lo;
    const v = Math.round((lo + (hi - lo) * (pos - Math.floor(pos))) / 10) * 10;
    if (out.length === 0 || v > (out[out.length - 1] ?? -Infinity)) out.push(v);
  }
  return out;
}

export function classOf(value: number, breaks: readonly number[]): number {
  let i = 0;
  while (i < breaks.length && value >= (breaks[i] ?? Infinity)) i++;
  return i;
}

/** Couleur d'une valeur : classe → rampe (rééchantillonnée si moins de classes). */
export function colorOf(value: number, breaks: readonly number[]): Rgb {
  const n = breaks.length + 1;
  const k = classOf(value, breaks);
  const idx = n <= 1 ? RAMP.length - 1 : Math.round((k / (n - 1)) * (RAMP.length - 1));
  return RAMP[idx] ?? RAMP[RAMP.length - 1]!;
}

export interface LegendItem {
  color: string;
  label: string;
}

export function legend(breaks: readonly number[], fmt: (n: number) => string): LegendItem[] {
  const n = breaks.length + 1;
  return Array.from({ length: n }, (_, k) => {
    const lo = breaks[k - 1];
    const hi = breaks[k];
    const color = hex(colorOf(lo ?? (hi ?? 0) - 1, breaks));
    const label =
      lo === undefined && hi !== undefined
        ? `moins de ${fmt(hi)}`
        : hi === undefined && lo !== undefined
          ? `${fmt(lo)} et plus`
          : lo !== undefined && hi !== undefined
            ? `de ${fmt(lo)} à ${fmt(hi)}`
            : "toutes valeurs";
    return { color, label };
  });
}
