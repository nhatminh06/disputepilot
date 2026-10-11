export function allowedBackend(base: string, compose: boolean): boolean {
  return compose ? base === 'http://backend:8000' : /^http:\/\/127\.0\.0\.1:800[01]$/.test(base);
}
