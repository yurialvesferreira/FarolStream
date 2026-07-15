/** @type {import('next').NextConfig} */
const nextConfig = {
  // Gera um server.js autocontido — a imagem final do Docker não precisa
  // de node_modules completo (ver src/frontend/Dockerfile).
  output: 'standalone',
};

export default nextConfig;
