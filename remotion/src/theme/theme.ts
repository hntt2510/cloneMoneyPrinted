import { Theme } from '../types';

export const defaultTheme: Theme = {
  background: '#0B0F19',
  surface: '#151D2E',
  surfaceBorder: 'rgba(255, 255, 255, 0.08)',
  primary: '#3B82F6',
  accent: '#60A5FA',
  positive: '#10B981',
  negative: '#EF4444',
  warning: '#F59E0B',
  text: '#F8FAFC',
  muted: '#94A3B8',
  border: 'rgba(255, 255, 255, 0.12)',
};

export const defaultFontFamily =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

export function resolveTheme(custom?: Partial<Theme>): Theme {
  return {
    ...defaultTheme,
    ...(custom || {}),
  };
}
