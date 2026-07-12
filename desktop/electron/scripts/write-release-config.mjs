import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputPath = path.join(projectDir, 'app-dist', 'release-config.json');
const updateUrl = String(process.env.CANVASHUB_UPDATE_URL || '').trim().replace(/\/+$/, '');
const upscaleManifestUrl = String(
  process.env.CANVASHUB_UPSCALE_MANIFEST_URL
  || (updateUrl ? `${updateUrl}/upscale-manifest.json` : '')
).trim();

await mkdir(path.dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify({
  update_url: updateUrl,
  upscale_manifest_url: upscaleManifestUrl,
}, null, 2)}\n`, 'utf8');

console.log(`Release configuration: ${outputPath}`);
console.log(`Update URL: ${updateUrl || '(not configured)'}`);
console.log(`Upscale manifest: ${upscaleManifestUrl || '(not configured)'}`);
