const nf = new Intl.NumberFormat('en-GB')
const fixed = (digits: number) => new Intl.NumberFormat('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const int = (n: number) => nf.format(Math.round(n))

export const pct = (x: number | null | undefined, digits = 1) =>
  x == null ? '–' : new Intl.NumberFormat('en-GB', { style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(x)

export const usd = (x: number) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: x < 0.01 ? 4 : 2,
    maximumFractionDigits: x < 0.01 ? 4 : 2,
  }).format(x)

export const size = (gb: number) => (gb < 1 ? `${fixed(1).format(gb * 1000)} MB` : `${fixed(1).format(gb)} GB`)

export const ms = (x: number | null | undefined) => (x == null ? '–' : `${nf.format(Math.round(x))} ms`)

export const shortDay = (day: string) =>
  new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(`${day}T00:00:00Z`))

export const PRICE_CLASS: Record<string, string> = {
  PriceClass_100: 'Price class 100',
  PriceClass_200: 'Price class 200',
  PriceClass_All: 'All edge locations',
}
