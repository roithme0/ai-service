const TOKEN_FORMAT = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});

export function formatTokens(tokens: number): string {
  return TOKEN_FORMAT.format(tokens);
}
