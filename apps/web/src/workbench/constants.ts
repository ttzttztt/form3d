export const wholeImage = { x: 0, y: 0, width: 1, height: 1 };
export const templateNames: Record<string, string> = {
  shelf: '开放置物架',
  table: '简约桌 / 边几',
  cabinet: '规则双门柜',
};
export const colors = ['#b79370', '#dfd1bd', '#f3f0e9', '#707d6a', '#41434b', '#b66c52'];
export const routeNames = {
  local: '本地自动生成',
  assistant: '对话看图建模',
  template: '手动结构工具',
  meshy: '云端图生 3D',
};
export type Panel = 'history' | 'assets' | 'help' | 'settings' | 'report' | null;
