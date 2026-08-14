import { bundle } from '@remotion/bundler';
import { renderMedia, selectComposition } from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const args = process.argv.slice(2);
  let specPath = null;
  let outputPath = null;
  let compositionId = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--spec' && i + 1 < args.length) {
      specPath = args[i + 1];
      i++;
    } else if (args[i] === '--output' && i + 1 < args.length) {
      outputPath = args[i + 1];
      i++;
    } else if (args[i] === '--composition' && i + 1 < args.length) {
      compositionId = args[i + 1];
      i++;
    }
  }

  if (!specPath || !outputPath) {
    console.error('Error: --spec and --output arguments are required');
    process.exit(1);
  }

  const absoluteSpecPath = path.resolve(specPath);
  const absoluteOutputPath = path.resolve(outputPath);

  if (!fs.existsSync(absoluteSpecPath)) {
    console.error(`Error: spec file does not exist: ${absoluteSpecPath}`);
    process.exit(1);
  }

  const specContent = fs.readFileSync(absoluteSpecPath, 'utf8');
  let specData;
  try {
    specData = JSON.parse(specContent);
  } catch (err) {
    console.error(`Error parsing spec JSON: ${err.message}`);
    process.exit(1);
  }

  if (!compositionId) {
    compositionId = specData.group_id ? 'Group' : 'Scene';
  }

  // Ensure output directory exists
  const outDir = path.dirname(absoluteOutputPath);
  fs.mkdirSync(outDir, { recursive: true });

  const entryPoint = path.resolve(__dirname, '../src/index.ts');

  // Bundle Remotion project
  const bundleLocation = await bundle({
    entryPoint,
    webpackOverride: (config) => config,
  });

  // Select composition with input props
  const composition = await selectComposition({
    serveUrl: bundleLocation,
    id: compositionId,
    inputProps: specData,
  });

  // Render MP4 video
  await renderMedia({
    composition,
    serveUrl: bundleLocation,
    codec: 'h264',
    outputLocation: absoluteOutputPath,
    inputProps: specData,
    imageFormat: 'jpeg',
    pixelFormat: 'yuv420p',
    crf: 18,
    muted: true,
    disallowParallelEncoding: false,
    scale: 1,
  });

  if (!fs.existsSync(absoluteOutputPath) || fs.statSync(absoluteOutputPath).size === 0) {
    console.error(`Error: output file is missing or empty after render: ${absoluteOutputPath}`);
    process.exit(1);
  }

  console.log(`Render succeeded: ${absoluteOutputPath}`);
  process.exit(0);
}

main().catch((err) => {
  console.error(`Remotion render error: ${err.stack || err.message || err}`);
  process.exit(1);
});
