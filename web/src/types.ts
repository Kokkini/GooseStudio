export type WorkflowKind = 'lite-upscale' | 'text-to-image' | 'image-edit' | 'try-on' | 'character-swap' | 'image-to-3d' | 'voxelize'
export type WorkloadKind = 'image' | 'video'
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
}

export interface ModalCredentials {
  tokenId: string
  tokenSecret: string
  workspace: string
}

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
  workflow?: WorkflowKind
  completed_at?: string
}

export type Workflow = Record<string, { inputs: Record<string, unknown>; class_type: string; _meta?: { title?: string } }>
