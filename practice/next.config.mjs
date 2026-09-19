/** @type {import('next').NextConfig} */
const config = {
  poweredByHeader: false,
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'no-referrer' },
      { key: 'Permissions-Policy', value: 'microphone=(self), camera=()' },
      { key: 'X-Frame-Options', value: 'DENY' },
    ] }];
  },
};
export default config;
