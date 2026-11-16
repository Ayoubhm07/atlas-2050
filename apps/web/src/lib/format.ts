/** Formats français. Aucun tiret cadratin : les intervalles s'écrivent « de X à Y ». */
const NBSP = " ";

const int = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const one = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function nombre(n: number): string {
  return int.format(n);
}

export function euros(n: number): string {
  return `${int.format(n)}${NBSP}€`;
}

export function eurosM2(n: number): string {
  return `${int.format(n)}${NBSP}€/m²`;
}

/** Pourcentage signé, une décimale : « +22,5 % », « −3,6 % » (signe moins typographique). */
export function pctSigne(n: number): string {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${one.format(Math.abs(n))}${NBSP}%`;
}

export function pct(n: number): string {
  return `${one.format(n)}${NBSP}%`;
}

export function fourchetteEuros(p10: number, p90: number): string {
  return `de ${euros(p10)} à ${euros(p90)}`;
}

export function dateLongue(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  const s = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(d);
  return s.replace(/^1 /, "1er ");
}

/** « de Bordeaux », « d'Arcachon », « d'Hourtin » : élision devant voyelle ou h muet. */
export function deNom(nom: string): string {
  return /^[aeiouyàâäéèêëîïôöùûüh]/i.test(nom) ? `d'${nom}` : `de ${nom}`;
}

/** Coordonnées lisibles : « 44,8378 N, 0,5792 O ». */
export function coordonnees(lat: number, lon: number): string {
  const f = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  return `${f.format(Math.abs(lat))}${NBSP}${lat >= 0 ? "N" : "S"}, ${f.format(Math.abs(lon))}${NBSP}${lon >= 0 ? "E" : "O"}`;
}
