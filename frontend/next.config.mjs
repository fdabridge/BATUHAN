/** @type {import('next').NextConfig} */
const backendOrigin = (
  process.env.API_URL
  || process.env.NEXT_PUBLIC_API_URL
  || 'http://localhost:8000'
).replace(/\/$/, '')

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/audit-plan/:path*',
        destination: `${backendOrigin}/audit-plan/:path*`,
      },
    ]
  },
  webpack: (config) => {
    // pdfjs-dist optionally imports native Node modules (canvas, encoding)
    // that don't exist in a browser/webpack context — alias them to false
    // so webpack skips them instead of failing the build.
    config.resolve.alias.canvas = false;
    config.resolve.alias.encoding = false;
    return config;
  },
}

export default nextConfig
