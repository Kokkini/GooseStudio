import type { Workflow, WorkflowKind } from './types.ts'

type ComfyWorkflowKind = Exclude<WorkflowKind, 'voxelize'>

const urls: Record<ComfyWorkflowKind, URL> = {
  'lite-upscale': new URL('../workflows/lite-upscale.json', import.meta.url),
  'text-to-image': new URL('../workflows/z-image-turbo.json', import.meta.url),
  'image-edit': new URL('../workflows/qwen-image-edit.json', import.meta.url),
  'try-on': new URL('../workflows/qwen-virtual-try-on.json', import.meta.url),
  'character-swap': new URL('../workflows/wan-character-swap.json', import.meta.url),
  'image-to-3d': new URL('../workflows/image-to-3d.json', import.meta.url),
  'image-to-3d-v2': new URL('../workflows/image-to-3d-v2.json', import.meta.url),
}

const maxSeed = 9_007_199_254_740_991

async function template(kind: ComfyWorkflowKind): Promise<Workflow> {
  const response = await fetch(urls[kind])
  if (!response.ok) throw new Error(`Could not load the ${kind} workflow`)
  return response.json()
}

function seed(value?: number) {
  return value || Math.floor(Math.random() * maxSeed) + 1
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function namespace(workflow: Workflow, prefix: string, jobId: string) {
  Object.values(workflow).forEach((node) => {
    const current = node.inputs.filename_prefix
    if (typeof current === 'string' && current.startsWith(prefix)) {
      node.inputs.filename_prefix = current.replace(prefix, `${prefix}${jobId}/`)
    }
  })
}

export interface ImageEditValues {
  prompt: string
  negativePrompt: string
  mode: 'speed' | 'quality'
  speedSteps: number
  qualitySteps: number
  seed: number
}

export async function imageEdit(values: ImageEditValues, names: string[], jobId: string) {
  const workflow = await template('image-edit')
  workflow['78'].inputs.image = names[0]
  for (const [index, nodeId] of [['1', '469'], ['2', '477']] as const) {
    const name = names[Number(index)]
    if (name) workflow[nodeId].inputs.image = name
    else {
      delete workflow['433:111'].inputs[`image${Number(index) + 1}`]
      delete workflow['433:110'].inputs[`image${Number(index) + 1}`]
      delete workflow[nodeId]
    }
  }
  workflow['433:111'].inputs.prompt = values.prompt.trim()
  workflow['433:110'].inputs.prompt = values.negativePrompt.trim()
  workflow['433:436'].inputs.value = clamp(values.speedSteps, 2, 12)
  workflow['433:438'].inputs.value = clamp(values.qualitySteps, 8, 32)
  workflow['433:443'].inputs.value = values.mode === 'speed'
  workflow['433:3'].inputs.seed = seed(values.seed)
  namespace(workflow, 'qwen_image_edit/', jobId)
  return [workflow]
}

export async function liteUpscale(name: string, jobId: string) {
  const workflow = await template('lite-upscale')
  workflow['1'].inputs.image = name
  workflow['4'].inputs.filename_prefix = `lite/${jobId}/Final`
  return [workflow]
}

export async function imageTo3d(name: string, jobId: string) {
  const workflow = await template('image-to-3d')
  workflow['14'].inputs.image = name
  workflow['57'].inputs.filename_prefix = `mesh/${jobId}/hy_mesh`
  return [workflow]
}

export type ImageTo3dV2Model = 'trellis2' | 'pixal3d'

export async function imageTo3dV2(name: string, jobId: string, model: ImageTo3dV2Model = 'trellis2') {
  const workflow = await template('image-to-3d-v2')
  workflow['122'].inputs.image = name
  workflow['316'].inputs.value = model === 'trellis2'
  workflow['322'].inputs.filename_prefix = `mesh/${jobId}/${model === 'trellis2' ? 'trellis2' : 'pixal3d'}`
  return [workflow]
}

export interface TextToImageValues {
  prompt: string
  width: number
  height: number
  steps: number
  seed: number
}

export async function textToImage(values: TextToImageValues, jobId: string) {
  const workflow = await template('text-to-image')
  workflow['57:27'].inputs.text = values.prompt.trim()
  workflow['57:13'].inputs.width = clamp(values.width, 512, 1536)
  workflow['57:13'].inputs.height = clamp(values.height, 512, 1536)
  workflow['57:3'].inputs.steps = clamp(values.steps, 4, 12)
  workflow['57:3'].inputs.seed = seed(values.seed)
  workflow['9'].inputs.filename_prefix = `z-image-turbo/${jobId}/Final`
  return [workflow]
}

export interface TryOnValues {
  mode: 'speed' | 'quality'
  speedSteps: number
  qualitySteps: number
  count: number
}

export async function tryOn(values: TryOnValues, names: string[], jobId: string) {
  const workflows: Workflow[] = []
  for (let i = 0; i < clamp(values.count, 1, 6); i += 1) {
    const workflow = await template('try-on')
    workflow['78'].inputs.image = names[0]
    workflow['469'].inputs.image = names[1]
    workflow['433:436'].inputs.value = clamp(values.speedSteps, 2, 12)
    workflow['433:438'].inputs.value = clamp(values.qualitySteps, 8, 32)
    workflow['433:443'].inputs.value = values.mode === 'speed'
    workflow['433:3'].inputs.seed = seed()
    namespace(workflow, 'qwen_image_edit/', jobId)
    workflows.push(workflow)
  }
  return workflows
}

export interface CharacterSwapValues {
  width: number
  height: number
  steps: number
  seed: number
  maskGrow: number
  objectDescription: string
  characterOnly: boolean
  upscale: boolean
}

export async function characterSwap(values: CharacterSwapValues, names: string[], jobId: string) {
  const workflow = await template('character-swap')
  const [video, character, voice] = names
  workflow['301'].inputs.video = video
  workflow['360'].inputs.image = character
  workflow['159'].inputs.value = values.width
  workflow['160'].inputs.value = values.height
  workflow['548:537'].inputs.seed = seed(values.seed)
  workflow['550'].inputs.value = clamp(values.steps, 1, 6)
  workflow['571'].inputs.value = 161
  workflow['548:537'].inputs.cfg = 1
  workflow['548:537'].inputs.sampler_name = 'euler'
  workflow['548:537'].inputs.scheduler = 'simple'
  workflow['548:537'].inputs.denoise = 1
  workflow['637'].inputs.value = 10
  workflow['635'].inputs.value = 99999
  workflow['605'].inputs.value = 0
  workflow['657'].inputs.value = false
  workflow['700'].inputs.value = values.maskGrow
  workflow['701'].inputs.value = values.objectDescription.trim() || 'bag'
  workflow['753'].inputs.value = Boolean(voice)
  workflow['751'].inputs.audio = voice || video
  delete workflow['751'].inputs.audioUI
  workflow['757'].inputs.value = values.characterOnly
  workflow['787'].inputs.value = values.upscale
  if (workflow['793']) workflow['793'].inputs.value = false
  namespace(workflow, 'char_swap/', jobId)
  return [workflow]
}

export const outputNodes: Record<WorkflowKind, string[]> = {
  'lite-upscale': ['4'],
  'text-to-image': ['9'],
  'image-edit': ['472'],
  'try-on': ['472'],
  'character-swap': ['368'],
  'image-to-3d': ['57'],
  'image-to-3d-v2': ['322'],
  voxelize: [],
}
