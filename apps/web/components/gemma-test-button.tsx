'use client';

import { useState } from 'react';

export function GemmaTestButton() {
  const [loading, setLoading] = useState(false);
  const [prompt, setPrompt] = useState(
    'Give me 3 concise ideas to improve a trading decision dashboard UI.',
  );
  const [text, setText] = useState('');

  async function handleClick() {
    try {
      setLoading(true);
      setText('');

      const res = await fetch('/api/gemma', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      });

      const data = await res.json();
      setText(data.text ?? data.error ?? 'No response');
    } catch {
      setText('Request failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <section
      className="card"
      style={{
        marginTop: 20,
        padding: 20,
        borderRadius: 16,
        background: 'linear-gradient(180deg, rgba(15,23,42,0.98) 0%, rgba(10,18,35,0.98) 100%)',
        border: '1px solid rgba(255,255,255,0.08)',
        boxShadow: '0 10px 30px rgba(0,0,0,0.25)',
      }}
    >
      <div style={{ marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 28, fontWeight: 700 }}>Gemma test</h2>
        <p
          style={{
            margin: '8px 0 0',
            color: 'rgba(255,255,255,0.7)',
            fontSize: 14,
          }}
        >
          Try prompts and get quick AI feedback inside your dashboard.
        </p>
      </div>

      <div
        style={{
          display: 'grid',
          gap: 12,
        }}
      >
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={5}
          placeholder="Type your prompt..."
          style={{
            width: '100%',
            padding: 14,
            borderRadius: 12,
            border: '1px solid rgba(255,255,255,0.12)',
            background: 'rgba(255,255,255,0.04)',
            color: 'white',
            fontSize: 15,
            lineHeight: 1.5,
            resize: 'vertical',
            outline: 'none',
          }}
        />

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            onClick={handleClick}
            disabled={loading || !prompt.trim()}
            style={{
              padding: '10px 16px',
              borderRadius: 10,
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 600,
              fontSize: 14,
              background: loading ? '#334155' : '#2563eb',
              color: 'white',
              opacity: loading ? 0.8 : 1,
            }}
          >
            {loading ? 'Thinking...' : 'Run prompt'}
          </button>

          <button
            onClick={() => setPrompt('')}
            type="button"
            style={{
              padding: '10px 16px',
              borderRadius: 10,
              border: '1px solid rgba(255,255,255,0.12)',
              background: 'transparent',
              color: 'white',
              cursor: 'pointer',
            }}
          >
            Clear
          </button>
        </div>

        <div
          style={{
            minHeight: 140,
            padding: 16,
            borderRadius: 12,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
          }}
        >
          {text ? (
            <div
              style={{
                whiteSpace: 'pre-wrap',
                lineHeight: 1.7,
                fontSize: 15,
                color: 'rgba(255,255,255,0.96)',
              }}
            >
              {text}
            </div>
          ) : (
            <p
              style={{
                margin: 0,
                color: 'rgba(255,255,255,0.5)',
                fontSize: 14,
              }}
            >
              Response will appear here.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
