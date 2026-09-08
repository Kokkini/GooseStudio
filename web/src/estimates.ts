import type { WorkflowKind } from './types.ts'

// Modal's standard compute prices, in credits per second, checked against the
// public pricing page on 2026-08-30. These are only estimates: Modal can
// change prices, and actual billing also includes resources intentionally not
// included here (memory, storage, and network).
const L40S_RATE = 0.000542
const H100_RATE = 0.001097
const CPU_CORE_RATE = 0.0000131
const VOXEL_CPU_CORES = 2
const MINIMUM_ESTIMATE = 0.01

// Measured on Modal L40S with the default 1024x1024, 8-step workflow:
// 21.29s inside ComfyUI plus the observed ~40s cold startup.
const TEXT_TO_IMAGE_SECONDS = 61.29
const IMAGE_EDIT_SECONDS = 120
// Measured on Modal L40S with image_to_3d.png, 32 steps, guidance 6,
// num_chunks 16000, and the RepairLongEdgeOutliers node enabled: 198.04s
// inside ComfyUI plus the observed ~40s cold startup.
const IMAGE_TO_3D_SECONDS = 238.04
// Initial Trellis 2 estimate until the new workflow has a Modal benchmark.
// It is intentionally conservative because Trellis 2 runs several shape,
// texture, and mesh-processing stages in one GPU job.
const IMAGE_TO_3D_V2_SECONDS = 360
const LITE_UPSCALE_SECONDS = 30
// Standalone CPU voxelizer measurements for 3d_to_voxel.glb. The first value
// includes Modal's cold function overhead; use a piecewise fit between the
// measured 64/128/256 resolution points. The image-to-3D post-process runs in
// the already-running L40S worker, so it uses the converter-only timings.
const VOXELIZE_MEASUREMENTS = [
  [64, 23.05],
  [128, 23.23],
  [256, 40.78],
] as const
const VOXELIZE_POSTPROCESS_MEASUREMENTS = [
  [64, 14.86],
  [128, 19.51],
  [256, 37.47],
] as const
const VOXELIZE_MAXIMUM_RESOLUTION = 256

export interface WorkflowEstimate {
  seconds: number
  credits: number
  resource: string
}

interface EstimateOptions {
  width?: number
  height?: number
  count?: number
  durationSeconds?: number | null
  upscale?: boolean
  voice?: boolean
  voxelize?: boolean
  voxelResolution?: number
}

function estimate(seconds: number, rate: number, resource: string): WorkflowEstimate {
  return {
    seconds,
    credits: Math.max(MINIMUM_ESTIMATE, seconds * rate),
    resource,
  }
}

function interpolateMeasuredSeconds(
  resolution: number,
  measurements: readonly (readonly [number, number])[],
): number {
  const boundedResolution = Math.max(1, Math.min(VOXELIZE_MAXIMUM_RESOLUTION, resolution))
  if (boundedResolution <= measurements[0][0]) return measurements[0][1]
  for (let index = 1; index < measurements.length; index += 1) {
    const [upperResolution, upperSeconds] = measurements[index]
    const [lowerResolution, lowerSeconds] = measurements[index - 1]
    if (boundedResolution <= upperResolution) {
      const fraction = (boundedResolution - lowerResolution) / (upperResolution - lowerResolution)
      return lowerSeconds + fraction * (upperSeconds - lowerSeconds)
    }
  }
  return measurements[measurements.length - 1][1]
}

function voxelizeSeconds(resolution: number): number {
  return interpolateMeasuredSeconds(resolution, VOXELIZE_MEASUREMENTS)
}

function voxelizePostprocessSeconds(resolution: number): number {
  return interpolateMeasuredSeconds(resolution, VOXELIZE_POSTPROCESS_MEASUREMENTS)
}

export function estimateWorkflow(workflow: WorkflowKind, options: EstimateOptions = {}): WorkflowEstimate | null {
  switch (workflow) {
    case 'text-to-image': {
      const width = options.width ?? 1024
      const height = options.height ?? 1024
      const pixelScale = (width * height) / (1024 * 1024)
      return estimate(TEXT_TO_IMAGE_SECONDS * pixelScale, L40S_RATE, 'L40S')
    }
    case 'image-edit':
      // Matches ComfyUIService's flat Qwen image-edit timing estimate.
      return estimate(IMAGE_EDIT_SECONDS, L40S_RATE, 'L40S')
    case 'try-on': {
      // Matches ComfyUIService: the first output loads the model and each
      // additional output reuses it.
      const count = Math.max(1, Math.round(options.count ?? 1))
      return estimate(100 + 30 * (count - 1), L40S_RATE, 'L40S')
    }
    case 'character-swap': {
      const duration = options.durationSeconds
      if (!duration || !Number.isFinite(duration) || duration <= 0) return null

      // Matches ComfyUIService's Modal/H100 estimate. The workflow renders in
      // five-second chunks, includes the baked-node cold start, and applies its
      // 20% safety buffer.
      const billedDuration = Math.ceil(duration / 5) * 5
      const perInputSecond = 16 + 2.3 * 4 + 9.8 * Number(Boolean(options.upscale)) + 2.4 * Number(Boolean(options.voice))
      const seconds = (40 + billedDuration * perInputSecond) * 1.2
      return estimate(seconds, H100_RATE, 'H100')
    }
    case 'image-to-3d': {
      const voxelSeconds = options.voxelize
        ? voxelizePostprocessSeconds(options.voxelResolution ?? 128)
        : 0
      return estimate(IMAGE_TO_3D_SECONDS + voxelSeconds, L40S_RATE, 'L40S')
    }
    case 'image-to-3d-v2': {
      const voxelSeconds = options.voxelize
        ? voxelizePostprocessSeconds(options.voxelResolution ?? 128)
        : 0
      return estimate(IMAGE_TO_3D_V2_SECONDS + voxelSeconds, L40S_RATE, 'L40S')
    }
    case 'voxelize':
      return estimate(voxelizeSeconds(options.voxelResolution ?? 128), CPU_CORE_RATE * VOXEL_CPU_CORES, '2 CPU cores')
    case 'lite-upscale':
      return estimate(LITE_UPSCALE_SECONDS, L40S_RATE, 'L40S')
    default:
      return null
  }
}

export function formatCreditEstimate(credits: number): string {
  return Math.max(MINIMUM_ESTIMATE, credits).toFixed(2)
}
