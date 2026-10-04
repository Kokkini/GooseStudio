export type WorkflowKind = 'lite-upscale' | 'text-to-image' | 'image-edit' | 'try-on' | 'character-swap' | 'image-to-3d' | 'image-to-3d-v2' | 'voxelize' | 'unimate-animation'
export type WorkloadKind = 'image' | 'image-to-3d' | 'video'
export type JobState = 'idle' | 'uploading' | 'preparing' | 'queued' | 'running' | 'completed' | 'failed'

export interface VoxelizationOptions {
  type: 'voxelize'
  resolution: number
}

export interface RuntimeConfig {
  baseUrl: string
  apiKey: string
  modalWorkspace?: string
  modalEnvironment?: string
  hasSavedModalCredentials?: boolean
}

export type ModalSetupMode = 'setup' | 'update' | 'switch'

export type ModalAppVersionStatus =
  | { state: 'current'; appVersion: string }
  | { state: 'update-required'; appVersion: string; deployedVersion?: string }
  | { state: 'unsupported'; appVersion: string }

export interface ModalCredentials {
  tokenId: string
  tokenSecret: string
  workspace: string
}

export interface VolumeDownloadRequest {
  jobId: string
  relativePath: string
  filename: string
}

export interface ModalModelPreview {
  previewId: string | null
  src: string
}

export type AppUpdateCheckResult =
  | { state: 'available'; currentVersion: string; version: string }
  | { state: 'up-to-date'; currentVersion: string }
  | { state: 'unsupported'; currentVersion: string }

export type AppUpdateProgress =
  | { state: 'downloading'; percent: number; transferred: number; total: number | null }
  | { state: 'verifying' }
  | { state: 'installing' }
  | { state: 'cancelled' }
  | { state: 'error'; error: string }

export interface SetupStatus {
  state: 'idle' | 'running' | 'completed' | 'failed'
  lines: string[]
  returncode?: number | null
  progress?: { stage: string; current: number; total: number; message: string } | null
  error?: string | null
}

export interface WorkflowInstallStatus {
  state: 'idle' | 'running' | 'completed' | 'failed'
  workflow?: WorkflowKind
  current?: number
  total?: number
  message?: string
  error?: string
  details?: string[]
}

export interface WorkflowCapabilities {
  installed: WorkflowKind[]
  installation: WorkflowInstallStatus
}

export interface OutputFile {
  id: string
  node_id: string
  filename: string
  relative_path: string
  content_type: string
}

export interface Job {
  job_id: string
  status: string
  outputs: OutputFile[]
  error?: string
  message?: string
  workflow?: WorkflowKind
  completed_at?: string
}

export type Workflow = Record<string, { inputs: Record<string, unknown>; class_type: string; _meta?: { title?: string } }>
