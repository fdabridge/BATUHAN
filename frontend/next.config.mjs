/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
