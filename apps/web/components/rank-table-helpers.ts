export function signalBadgeClass(signalLabel: string) {
  if (signalLabel === 'strong') return 'green';
  if (signalLabel === 'watch') return 'blue';
  return '';
}

export function newsBadgeClass(newsSource: string) {
  if (newsSource === 'marketaux') return 'blue';
  if (newsSource === 'cache') return 'green';
  if (newsSource === 'skipped') return 'amber';
  return '';
}
