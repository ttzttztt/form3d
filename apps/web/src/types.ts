export interface Point {
  x: number;
  y: number;
}
export interface Target extends Point {
  width: number;
  height: number;
}
export interface Stroke {
  points: Point[];
  radius: number;
}
export interface UploadedImage {
  id: string;
  name: string;
  width: number;
  height: number;
  preview_url: string;
  analysis?: DetectionResult;
}
export interface DetectedObject {
  id: string;
  label: string;
  category: string;
  score: number;
  target: Target;
}
export interface DetectionResult {
  status: 'queued' | 'running' | 'completed' | 'failed';
  objects: DetectedObject[];
  duration_seconds?: number;
  error?: string;
}
export interface Sample {
  id: string;
  name: string;
  material: string;
  model_url: string;
  preview_url: string;
}
export interface Job {
  id: string;
  name: string;
  reference_image_ids?: string[];
  status: string;
  stage: string;
  created_at: string;
  error?: string;
  model_url?: string;
  prepared_url?: string;
  model_input_url?: string;
  foreground_url?: string;
  segmented_url?: string;
  segmentation_mask_url?: string;
  segmentation_overlay_url?: string;
  cleaned_url?: string;
  input_overlay_url?: string;
  input_quality_url?: string;
  attention_kind?: string;
  actual_engine?: 'triposr' | 'hunyuan-mini';
  output_quality_url?: string;
  output_quality?: {
    status: 'pass' | 'blocked';
    reasons: { code: string; message: string }[];
    warnings: string[];
  };
  output_attempts?: { index: number; engine: string; status: string; candidate_url: string }[];
  input_quality?: {
    status: 'pass' | 'blocked';
    reasons: { code: string; message: string }[];
    warnings: string[];
    removed_alpha_pixels: number;
    hidden_surface_completion: boolean;
  };
  provider_task_id?: string;
  provider_progress?: number;
  review_status: string;
  request: {
    image_id: string;
    reference_image_ids?: string[];
    route: Route;
    local_remove_background?: boolean;
    local_engine?: 'triposr' | 'hunyuan-mini';
    local_segmentation?: 'auto' | 'sam2' | 'basic';
    local_auto_retry?: boolean;
    object_category?: string;
    object_label?: string;
    object_id?: string;
    template: string;
    target: Target;
    strokes: Stroke[];
    color: string;
    levels: number;
    dimensions: { width: number; depth: number; height: number; confirmed: boolean };
  };
  metrics?: { parts: number; triangles: number; bytes: number; dimensions_m?: number[] };
  report?: { warnings: string[]; scale_status: string; checks: Record<string, string> };
  events: { at: string; stage: string; message: string }[];
  parts_plan?: { count: number; parts: { id: string; name: string; kind: string }[] };
  parts_overlay_url?: string;
}
export type Route = 'local' | 'assistant' | 'template' | 'meshy' | 'parts_first';

export interface PartsFirstStatus {
  available: boolean;
  missing: string[];
  categories: string[];
  generator: string;
  max_parts: number;
}

export interface Configuration {
  providers: {
    local: {
      available: boolean;
      model: string;
      device?: string;
      weights_ready: boolean;
      runtime_ready: boolean;
      engines?: Record<
        string,
        { available: boolean; model: string; output: string; inference_tested: boolean }
      >;
    };
    assistant: { available: boolean };
    template: { available: boolean };
    meshy: { available: boolean };
    parts_first?: PartsFirstStatus;
  };
  detection: { available: boolean; model: string; categories: string[] };
  target_segmentation?: { available: boolean; model: string; score_is_accuracy: boolean };
  input_preparation?: { available: boolean; model: string; hidden_surface_completion: boolean };
}

export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : body.detail?.[0]?.msg || message;
    } catch {
      /* A disconnected proxy may return plain text. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function post<T>(url: string, body: unknown = {}, headers: Record<string, string> = {}) {
  return api<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

export const statusLabels: Record<string, string> = {
  queued: '排队中',
  running: '处理中',
  awaiting_review: '待审核',
  completed: '已通过',
  failed: '处理失败',
  cancelled: '已取消',
  awaiting_input: '需要处理',
  awaiting_assistant: '待看图建模',
  rejected: '需修改',
};
