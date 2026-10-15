import {
  COCKPIT_URL,
  DEFAULT_URL,
  hostOf,
  isAcceptable,
  resolveCockpitUrl,
} from '../src/cockpitUrl';

describe('cockpitUrl', () => {
  it('accepts absolute http and https URLs only', () => {
    expect(isAcceptable('https://example.org/')).toBe(true);
    expect(isAcceptable('http://192.168.1.20:8002/')).toBe(true);
    expect(isAcceptable('HTTPS://EXAMPLE.ORG/')).toBe(true);
    expect(isAcceptable('file:///pkg/assets/index.html')).toBe(false);
    expect(isAcceptable('javascript:alert(1)')).toBe(false);
    expect(isAcceptable('https://')).toBe(false);
    expect(isAcceptable('https://a b')).toBe(false);
    expect(isAcceptable('https://a\u0001b')).toBe(false);
    expect(isAcceptable(undefined)).toBe(false);
    expect(isAcceptable('   ')).toBe(false);
  });

  it('falls through launch URL, build URL, default', () => {
    expect(resolveCockpitUrl('https://a.example/', 'https://b.example/')).toBe('https://a.example/');
    expect(resolveCockpitUrl(' https://a.example/ ', '')).toBe('https://a.example/');
    expect(resolveCockpitUrl('nope', 'https://b.example/')).toBe('https://b.example/');
    expect(resolveCockpitUrl(undefined, '')).toBe(DEFAULT_URL);
  });

  it('loads the public demo the Fire OS build defaults to', () => {
    expect(COCKPIT_URL).toBe(DEFAULT_URL);
    expect(DEFAULT_URL).toBe('https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/');
  });

  it('extracts the host for the offline screen', () => {
    expect(hostOf('https://h.example:8002/x')).toBe('h.example:8002');
    expect(hostOf('garbage')).toBe('garbage');
    expect(hostOf('https:///path')).toBe('https:///path');
  });
});
