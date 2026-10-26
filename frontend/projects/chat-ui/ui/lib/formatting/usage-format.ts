const COST_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumSignificantDigits: 3,
});

export function formatUsageCost(cost: string): string {
  return COST_FORMAT.format(Number(cost));
}
