// CloudFront logs carry ISO 3166-1 alpha-2 country codes; the world map (world-atlas) keys
// countries by ISO 3166-1 numeric code. Names are for the list beside the map.
export const COUNTRIES: Record<string, { numeric: string; name: string }> = {
  AE: { numeric: '784', name: 'United Arab Emirates' },
  AR: { numeric: '032', name: 'Argentina' },
  AU: { numeric: '036', name: 'Australia' },
  BR: { numeric: '076', name: 'Brazil' },
  CA: { numeric: '124', name: 'Canada' },
  DE: { numeric: '276', name: 'Germany' },
  FR: { numeric: '250', name: 'France' },
  GB: { numeric: '826', name: 'United Kingdom' },
  IE: { numeric: '372', name: 'Ireland' },
  IL: { numeric: '376', name: 'Israel' },
  IN: { numeric: '356', name: 'India' },
  JP: { numeric: '392', name: 'Japan' },
  KR: { numeric: '410', name: 'South Korea' },
  NL: { numeric: '528', name: 'Netherlands' },
  NZ: { numeric: '554', name: 'New Zealand' },
  SG: { numeric: '702', name: 'Singapore' },
  US: { numeric: '840', name: 'United States' },
  ZA: { numeric: '710', name: 'South Africa' },
  ZW: { numeric: '716', name: 'Zimbabwe' },
}

export const countryName = (code: string) => COUNTRIES[code]?.name ?? code
