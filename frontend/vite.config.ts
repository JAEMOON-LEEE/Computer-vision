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
});
