const DEFAULT_SCANNER_API_BASE = 'http://localhost:8005';

function isServerRuntime() {
  return typeof window === 'undefined';
}

export function getScannerApiBase() {
  return process.env.NEXT_PUBLIC_SCANNER_API_BASE || DEFAULT_SCANNER_API_BASE;
}

export function getServerReadHeaders(): HeadersInit {
  const headers = new Headers();
  const readToken = process.env.SCANNER_READ_API_TOKEN;

  if (isServerRuntime() && readToken) {
    headers.set('Authorization', `Bearer ${readToken}`);
  }

  return headers;
}

export async function readErrorMessage(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as {
      detail?: string;
      error?: { message?: string };
      message?: string;
    };

    if (typeof data.detail === 'string' && data.detail.trim()) {
      return data.detail;
    }

    if (typeof data.error?.message === 'string' && data.error.message.trim()) {
      return data.error.message;
    }

    if (typeof data.message === 'string' && data.message.trim()) {
      return data.message;
    }
  } catch {
    // Ignore parse failures and fall back to the HTTP status line.
  }

  return `Request failed: ${res.status} ${res.statusText}`;
}

export async function fetchScannerJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const readHeaders = getServerReadHeaders();

  new Headers(readHeaders).forEach((value, key) => {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  });

  let res: Response;

  try {
    res = await fetch(`${getScannerApiBase()}${path}`, {
      ...init,
      cache: 'no-store',
      headers,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : 'Unknown network error.';
    throw new Error(`Unable to reach scanner API: ${detail}`);
  }

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  try {
    return (await res.json()) as T;
  } catch {
    throw new Error(`Request returned invalid JSON for ${path}.`);
  }
}
