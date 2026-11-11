const KEY = 'parable.return';

export function rememberReturn(hash: string = window.location.hash) {
  try { sessionStorage.setItem(KEY, hash || '#market'); } catch { return; }
}

export function takeReturn(): string | null {
  try {
    const value = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return value;
  } catch {
    return null;
  }
}

export function goSignIn(navigate: (url: string) => void = url => window.location.assign(url)) {
  rememberReturn();
  navigate('/paypal/login');
}
