/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Next 14 的配置项名称，Next 15 才改名成顶层 serverExternalPackages
    serverComponentsExternalPackages: ["mysql2", "pdf-parse"],
    instrumentationHook: true,
  },
  webpack(config, { isServer }) {
    // serverComponentsExternalPackages 不作用于 instrumentation.ts 的依赖图，
    // 这里再显式 external 一次，避免 mysql2 的 node: 内置模块被 webpack 打包。
    if (isServer) {
      config.externals.push(({ request }, callback) => {
        if (
          request === "mysql2" ||
          request.startsWith("mysql2/") ||
          request === "pdf-parse" ||
          request.startsWith("pdf-parse/")
        ) {
          return callback(null, `commonjs ${request}`);
        }
        return callback();
      });
    }
    return config;
  },
};

export default nextConfig;
