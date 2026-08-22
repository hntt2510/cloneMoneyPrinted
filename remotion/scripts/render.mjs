import { bundle } from '@remotion/bundler';
import { renderMedia, selectComposition } from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ALLOWED_TEMPLATES = new Set([
  'number',
  'counter',
  'comparison',
  'timeline',
  'bar_chart',
  'line_chart',
  'threshold',
  'age_marker',
  'callout',
  'text',
  'breakdown',
  'pie',
  'donut',
  'gauge',
  'waterfall',
  'ranked_list',
  'area',
  'area_chart',
  'before_after',
  'stacked_bar',
  'diagram',
  'data_grid',
  'hybrid_broll',
  'metric_punch',
]);

function isPlainObject(obj) {
  return typeof obj === 'object' && obj !== null && !Array.isArray(obj);
}

function validateSpec(specData, compositionId) {
  if (compositionId !== 'Scene' && compositionId !== 'Group') {
    throw new Error(`Invalid composition ID: "${compositionId}". Must be "Scene" or "Group".`);
  }

  const fps = Number(specData.fps);
  if (!Number.isInteger(fps) || fps <= 0 || fps > 240) {
    throw new Error(`Invalid fps: ${specData.fps}. Must be a positive integer <= 240.`);
  }

  const width = Number(specData.width);
  const height = Number(specData.height);
  if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0) {
    throw new Error(`Invalid dimensions: width=${specData.width}, height=${specData.height}. Must be positive integers.`);
  }

  const durationInFrames = Number(specData.duration_in_frames);
  if (!Number.isInteger(durationInFrames) || durationInFrames <= 0) {
    throw new Error(`Invalid duration_in_frames: ${specData.duration_in_frames}. Must be a positive integer.`);
  }

  if (compositionId === 'Scene') {
    const template = (specData.template || '').trim().toLowerCase();
    if (!ALLOWED_TEMPLATES.has(template)) {
      throw new Error(
        `Unknown or disallowed template: "${specData.template}". Allowed templates: ${Array.from(ALLOWED_TEMPLATES).join(', ')}`
      );
    }
    if (!isPlainObject(specData.props)) {
      throw new Error(`Invalid props for Scene: must be a plain object, got ${typeof specData.props}`);
    }
  } else if (compositionId === 'Group') {
    if (!Array.isArray(specData.scenes) || specData.scenes.length === 0) {
      throw new Error('Group specification must contain a non-empty "scenes" array.');
    }

    for (let i = 0; i < specData.scenes.length; i++) {
      const scene = specData.scenes[i];
      if (!isPlainObject(scene)) {
        throw new Error(`Group scene at index ${i} is not a valid object.`);
      }
      if (!scene.scene_id || typeof scene.scene_id !== 'string' || !scene.scene_id.trim()) {
        throw new Error(`Group scene at index ${i} has invalid or empty scene_id.`);
      }
      const template = (scene.template || '').trim().toLowerCase();
      if (!ALLOWED_TEMPLATES.has(template)) {
        throw new Error(
          `Group scene "${scene.scene_id}" has unknown template: "${scene.template}". Allowed templates: ${Array.from(ALLOWED_TEMPLATES).join(', ')}`
        );
      }
      if (!isPlainObject(scene.props)) {
        throw new Error(`Group scene "${scene.scene_id}" props must be a plain object.`);
      }
      const startFrame = Number(scene.start_frame);
      const endFrame = Number(scene.end_frame);
      const durationFrames = Number(scene.duration_frames);
      if (!Number.isInteger(startFrame) || startFrame < 0) {
        throw new Error(`Group scene "${scene.scene_id}" has invalid start_frame: ${scene.start_frame}`);
      }
      if (!Number.isInteger(endFrame) || endFrame <= startFrame) {
        throw new Error(`Group scene "${scene.scene_id}" has invalid end_frame: ${scene.end_frame}`);
      }
      if (!Number.isInteger(durationFrames) || durationFrames <= 0 || durationFrames !== (endFrame - startFrame)) {
        throw new Error(`Group scene "${scene.scene_id}" has invalid duration_frames: ${scene.duration_frames}`);
      }
    }
  }
}

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

  // Runtime validation before bundle and render
  try {
    validateSpec(specData, compositionId);
  } catch (valErr) {
    console.error(`Spec validation error: ${valErr.message}`);
    process.exit(1);
  }

  // Ensure output and public directories exist
  const outDir = path.dirname(absoluteOutputPath);
  fs.mkdirSync(outDir, { recursive: true });

  const publicDir = path.resolve(__dirname, '../public');
  if (!fs.existsSync(publicDir)) {
    fs.mkdirSync(publicDir, { recursive: true });
  }

  function resolveLocalAsset(props) {
    if (!props || !props.asset_path) return;
    const rawPath = props.asset_path;
    if (rawPath.startsWith('http://') || rawPath.startsWith('https://') || rawPath.startsWith('data:')) {
      return;
    }
    let cleanPath = rawPath;
    if (cleanPath.startsWith('file:///')) {
      cleanPath = cleanPath.slice(8);
    } else if (cleanPath.startsWith('file://')) {
      cleanPath = cleanPath.slice(7);
    }
    if (fs.existsSync(cleanPath)) {
      const ext = path.extname(cleanPath) || '.mp4';
      const baseName = path.basename(cleanPath, ext);
      const targetName = `asset_${Date.now()}_${baseName}${ext}`;
      const targetPath = path.join(publicDir, targetName);
      fs.copyFileSync(cleanPath, targetPath);
      props.asset_path = targetName;
    }
  }

  if (specData.props) {
    resolveLocalAsset(specData.props);
  }
  if (Array.isArray(specData.scenes)) {
    for (const s of specData.scenes) {
      if (s.props) resolveLocalAsset(s.props);
    }
  }

  const entryPoint = path.resolve(__dirname, '../src/index.ts');

  // Bundle Remotion project
  const bundleLocation = await bundle({
    entryPoint,
    publicDir,
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
    chromiumOptions: {
      args: [
        '--allow-file-access-from-files',
        '--disable-web-security',
        '--disable-features=IsolateOrigins,site-per-process',
      ],
    },
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
