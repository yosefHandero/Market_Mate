/**
 * @vitest-environment jsdom
 *
 * Regression guard for the app-router template wrapper. This wrapper is applied
 * to every route, including the error/404/500 prerenders that previously tripped
 * `useContext(null)` during `next build`. It must render its children safely even
 * when no framer-motion provider is mounted above it, and it must not require a
 * context that is absent during static prerender.
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Template from '@/app/template';

describe('app/template', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders children with no framer-motion provider above it', () => {
    render(
      <Template>
        <span data-testid="child">dashboard content</span>
      </Template>,
    );
    expect(screen.getByTestId('child')).toHaveTextContent('dashboard content');
  });

  it('renders children when reduced motion is preferred', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockImplementation((query: string) => ({
        matches: true,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );

    render(
      <Template>
        <span data-testid="child">reduced motion content</span>
      </Template>,
    );
    expect(screen.getByTestId('child')).toHaveTextContent('reduced motion content');
  });
});
