import { api } from '../types';
import type { Job } from '../types';
import {
  ArrowUpRight,
  Box,
  Boxes,
  CircleHelp,
  History,
  Layers3,
  Settings2,
  WandSparkles,
} from 'lucide-react';
import type { Workbench } from './useWorkbench';

export default function Sidebar({ wb }: { wb: Workbench }) {
  const { samples, jobs, setJobs, panel, setPanel, connected, active, handleError } = wb;
  return (
    <>
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="FORM 首页">
          <span className="brand-mark">
            <Box size={23} strokeWidth={1.6} />
          </span>
          <span>
            FORM<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">CREATIVE WORKSPACE</div>
        <nav>
          <button
            aria-label="创作工作台"
            className={!panel ? 'nav-item selected' : 'nav-item'}
            onClick={() => setPanel(null)}
          >
            <WandSparkles size={18} />
            <span>创作工作台</span>
            <span className="nav-active-dot" />
          </button>
          <button
            aria-label="资产库"
            className={panel === 'assets' ? 'nav-item selected' : 'nav-item'}
            onClick={() => setPanel('assets')}
          >
            <Boxes size={18} />
            <span>资产库</span>
            <span className="nav-count">
              {jobs.filter((item) => item.status === 'completed').length + samples.length}
            </span>
          </button>
          <button
            aria-label="任务记录"
            className={panel === 'history' ? 'nav-item selected' : 'nav-item'}
            onClick={() => {
              setPanel('history');
              void api<Job[]>('/api/jobs').then(setJobs).catch(handleError);
            }}
          >
            <History size={18} />
            <span>任务记录</span>
            {jobs.length > 0 && <span className="nav-count">{jobs.length}</span>}
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className="local-card-icon">
              <Layers3 size={19} />
            </span>
            <strong>从灵感，到立体</strong>
            <p>
              让商品的每个角度
              <br />
              都值得被看见。
            </p>
            <span className="local-version">
              LOCAL PREVIEW <i>v0.1</i>
            </span>
          </div>
          <button aria-label="使用指南" className="nav-item" onClick={() => setPanel('help')}>
            <CircleHelp size={18} />
            <span>使用指南</span>
            <ArrowUpRight size={14} />
          </button>
          <button aria-label="服务设置" className="nav-item" onClick={() => setPanel('settings')}>
            <Settings2 size={18} />
            <span>服务设置</span>
          </button>
          <div className="user-block">
            <div className="avatar">L</div>
            <div>
              <strong>本地工作空间</strong>
              <span>
                <i className={connected ? 'online' : 'offline'} />
                {connected ? '服务已连接' : '连接检查中'}
              </span>
            </div>
            <span className="user-local">本地</span>
          </div>
        </div>
      </aside>
    </>
  );
}
