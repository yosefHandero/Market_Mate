'use client';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main>
      <section className="card">
        <h1>Something went wrong</h1>
        <p className="negative" style={{ marginBottom: 12 }}>
          {error.message || 'Unexpected dashboard error.'}
        </p>
        <button className="button" onClick={reset}>
          Try again
        </button>
      </section>
    </main>
  );
}
