/**
 * @vitest-environment jsdom
 */
import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';
import RootLayout from '@/app/layout';

describe('RootLayout navigation', () => {
  it('links Actions to / and History to /history (dashboard surface only)', () => {
    render(
      React.createElement(
        RootLayout,
        null,
        React.createElement('span', null, 'child'),
      ),
    );
    expect(screen.getByRole('link', { name: 'Actions' }).getAttribute('href')).toBe('/');
    expect(screen.getByRole('link', { name: 'History' }).getAttribute('href')).toBe('/history');
    expect(screen.queryByRole('link', { name: 'Journal' })).toBeNull();
  });
});
