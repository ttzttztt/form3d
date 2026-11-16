// Optional full glTF validation for the local worker. Never loads remote files.
const fs = require('node:fs');
const path = require('node:path');
let validator;
for (const location of [
  'gltf-validator',
  '../.tools/reference_furniture/node_modules/gltf-validator',
]) {
  try {
    validator = require(location);
    break;
  } catch {
    /* Try local prototype dependency. */
  }
}
if (!validator) {
  process.stdout.write(JSON.stringify({ status: 'not_run', reason: 'validator_not_installed' }));
  process.exit(0);
}
(async () => {
  const file = process.argv[2];
  const report = await validator.validateBytes(new Uint8Array(fs.readFileSync(file)), {
    uri: path.basename(file),
    maxIssues: 50,
    externalResourceFunction: () => Promise.reject(new Error('External resources are not allowed')),
  });
  process.stdout.write(
    JSON.stringify({
      status: report.issues.numErrors ? 'fail' : 'pass',
      errors: report.issues.numErrors,
      warnings: report.issues.numWarnings,
      messages: report.issues.messages,
    }),
  );
})().catch(() => {
  process.stderr.write('Validator could not inspect this asset');
  process.exitCode = 1;
});
