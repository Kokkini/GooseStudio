import type { Job, RuntimeConfig, VoxelizationOptions, Workflow, WorkflowCapabilities, WorkflowKind, WorkloadKind } from './types.ts'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`)
  return body as T
}

function url(config: RuntimeConfig, path: string) {
  return `${config.baseUrl.replace(/\/$/, '')}/${path}`
}

export function authHeaders(config: RuntimeConfig) {
  return { Authorization: `Bearer ${config.apiKey}` }
}

export function checkConnection(config: RuntimeConfig) {
  return request<{ status: string }>(url(config, 'auth-check'), { headers: authHeaders(config) })
}

export function getWorkflowCapabilities(config: RuntimeConfig) {
  return request<WorkflowCapabilities>(url(config, 'workflows'), { headers: authHeaders(config) })
}

export function installWorkflow(config: RuntimeConfig, workflow: WorkflowKind) {
  return request(url(config, 'workflows/install'), {
    method: 'POST',
    headers: { ...authHeaders(config), 'Content-Type': 'application/json' },
    body: JSON.stringify({ workflow }),
  })
}

export function uploadInputs(config: RuntimeConfig, jobId: string, files: Map<string, File>) {
  const form = new FormData()
  form.append('job_id', jobId)
  files.forEach((file, name) => form.append('files', file, name))
  return request(url(config, 'upload'), { method: 'POST', headers: authHeaders(config), body: form })
}

export function submitJob(config: RuntimeConfig, jobId: string, workflows: Workflow[], outputNodeIds: string[], workload: WorkloadKind, postprocess?: VoxelizationOptions) {
  return request(url(config, 'submit'), {
    method: 'POST',
    headers: { ...authHeaders(config), 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, workflows, output_node_ids: outputNodeIds, workload, ...(postprocess ? { postprocess } : {}) }),
  })
}

export function submitVoxelizationJob(config: RuntimeConfig, jobId: string, inputName: string, resolution: number) {
  return request(url(config, 'voxelize'), {
    method: 'POST',
    headers: { ...authHeaders(config), 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, input_name: inputName, resolution }),
  })
}

export function getJob(config: RuntimeConfig, jobId: string) {
  return request<Job>(`${url(config, 'status')}?job_id=${encodeURIComponent(jobId)}`, { headers: authHeaders(config) })
}

export function cancelJob(config: RuntimeConfig, jobId: string) {
  return request(url(config, 'cancel'), {
    method: 'POST',
    headers: { ...authHeaders(config), 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId }),
  })
}

export function deleteJob(config: RuntimeConfig, jobId: string) {
  return request(url(config, `jobs/${encodeURIComponent(jobId)}`), {
    method: 'DELETE',
    headers: authHeaders(config),
  })
}

export async function downloadOutput(config: RuntimeConfig, jobId: string, outputId: string) {
  const query = new URLSearchParams({ job_id: jobId, output_id: outputId })
  const response = await fetch(`${url(config, 'download')}?${query}`, { headers: authHeaders(config) })
  if (!response.ok) throw new Error(`Download failed (${response.status})`)
  return response.blob()
}
