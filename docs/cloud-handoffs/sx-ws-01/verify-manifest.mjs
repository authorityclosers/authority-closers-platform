// Verifies local package bytes only. No network and no receipt/customer data reads.
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const manifest = JSON.parse(await readFile(new URL('./manifest.json', import.meta.url), 'utf8'));
for (const file of manifest.files) {
  assert.match(file.path, /^(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+$/);
  assert.ok(!file.path.split('/').includes('..'));
  const bytes = await readFile(new URL(file.path, import.meta.url));
  assert.equal(bytes.length, file.bytes, file.path);
  assert.equal(createHash('sha256').update(bytes).digest('hex'), file.sha256, file.path);
}
console.log(`PASS: ${manifest.files.length} file SHA-256 values verified; manifest excludes itself.`);
