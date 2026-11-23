/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_CARTO_KEY?: string;
  readonly VITE_DEMO_TWIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
