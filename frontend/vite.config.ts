import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  envDir: "..",
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Unity WebGL 빌드(/demo용)는 빌드 중 파일이 잠겨 감시하면 서버가 죽는다. 정적 파일이라 감시가 필요 없다.
    watch: { ignored: ["**/public/unity/**"] },
  },
  // 발표 시연 외부 공유: npm run build 후 npm run preview -- --host 로 띄우고 Cloudflare 임시 터널로 연다.
  // 외부 사용자에게는 시연 검출 API(/demo)만 백엔드로 넘긴다(DB·카메라·키가 쓰이는 다른 API는 넘기지 않는다).
  preview: {
    port: 4173,
    strictPort: true,
    allowedHosts: [".trycloudflare.com"],
    proxy: { "/demo/": { target: "http://localhost:8000", changeOrigin: true } },
  },
});
