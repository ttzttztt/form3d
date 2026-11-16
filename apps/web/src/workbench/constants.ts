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
  parts_first: '部件优先生成',
};
export type Panel = 'history' | 'assets' | 'help' | 'settings' | 'report' | null;

export const partKindNames: Record<string, string> = {
  seat_cushion: '坐垫',
  back_cushion: '靠枕',
  bolster: '圆柱抱枕',
  backrest: '靠背',
  armrest: '扶手',
  frame: '座架 / 框架',
  body: '整体主体',
  leg: '支腿',
  tabletop: '桌面',
  door: '柜门',
  drawer: '抽屉',
  shelf: '层板',
  panel: '侧板 / 面板',
  other: '其他',
  unknown: '未确定',
};
