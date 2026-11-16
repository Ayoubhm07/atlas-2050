import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const config = [
  ...coreWebVitals,
  ...typescript,
  { ignores: [".next/**", "public/vendor/**", "node_modules/**", "test-results/**", "playwright-report/**", "reports/**", "next-env.d.ts"] },
];

export default config;
