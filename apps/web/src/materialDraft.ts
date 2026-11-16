export interface MaterialSettings {
  color: string;
  roughness: number;
  metalness: number;
  opacity: number;
  mode: string;
  textures: Record<string, string>;
  uvScale: number;
  uvRotation: number;
}
export interface MaterialDraft extends MaterialSettings {
  part_ids: string[];
}
export type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';
export function sameMaterial(a: MaterialSettings, b: MaterialSettings) {
  const stable = (v: MaterialSettings) =>
    JSON.stringify({ ...v, textures: Object.fromEntries(Object.entries(v.textures).sort()) });
  return stable(a) === stable(b);
}
