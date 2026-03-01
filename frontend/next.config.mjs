/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const backendBase = process.env.BACKEND_BASE_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendBase}/api/:path*`
      },
      {
        source: "/healthz",
        destination: `${backendBase}/healthz`
      }
    ];
  }
};

export default nextConfig;
