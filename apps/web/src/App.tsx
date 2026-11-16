import { Check, ChevronRight, CircleHelp, Plus, ShieldCheck, X } from 'lucide-react';
import { useWorkbench } from './workbench/useWorkbench';
import Sidebar from './workbench/Sidebar';
import InputPanel from './workbench/InputPanel';
import ResultPanel from './workbench/ResultPanel';
import ExamplesSection from './workbench/ExamplesSection';
import PanelModal from './workbench/PanelModal';

export default function App() {
  const wb = useWorkbench();
  const {
    job,
    setPanel,
    toast,
    setToast,
    setComparison,
    preparing,
    setPreparing,
    modelEditing,
    progress,
    reset,
  } = wb;
  return (
    <div className="app-shell">
      <Sidebar wb={wb} />

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间 <ChevronRight size={13} />
            <span>图片转 3D</span>
          </div>
          <div className="topbar-actions">
            <span className="local-pill">
              <span />
              本地工作台
            </span>
            <button className="icon-button" aria-label="使用帮助" onClick={() => setPanel('help')}>
              <CircleHelp size={19} />
            </button>
            <span className="topbar-divider" />
            <div className="mini-avatar">L</div>
          </div>
        </header>
        <main className={modelEditing ? 'editing-model' : ''}>
          <div className="page-intro">
            <div>
              <div className="eyebrow">
                <span /> IMAGE TO 3D
              </div>
              <h1>
                {modelEditing ? '查看与编辑模型' : '让图片，拥有更多角度'}
                <span>。</span>
              </h1>
              <p>
                {modelEditing
                  ? '先查看模型，再选择部件换颜色或材质。'
                  : '从一张参考图片开始，制作可旋转、可查看的商品模型。'}
              </p>
            </div>
            {modelEditing && (
              <button
                className="button secondary"
                onClick={() => {
                  setPreparing(true);
                  setComparison(false);
                }}
              >
                修改图片 / 重新生成
              </button>
            )}
            {preparing && job?.model_url && (
              <button className="button secondary" onClick={() => setPreparing(false)}>
                返回模型编辑
              </button>
            )}
            <button className="button secondary new-task" onClick={reset}>
              <Plus size={16} />
              新建任务
            </button>
          </div>
          {!modelEditing && (
            <div className="workflow">
              {['上传参考图', '准备图片', '生成模型', '审核与导出'].map((step, i) => (
                <div
                  key={step}
                  className={`workflow-step ${i <= progress ? 'reached' : ''} ${i === progress ? 'current' : ''}`}
                >
                  <span className="step-circle">
                    {i < progress ? <Check size={13} /> : `0${i + 1}`}
                  </span>
                  <span>{step}</span>
                  {i < 3 && <div className="step-line" />}
                </div>
              ))}
              <span className="workflow-note">
                <ShieldCheck size={14} />
                原图始终保留
              </span>
            </div>
          )}

          <div className="work-grid">
            <InputPanel wb={wb} />

            <ResultPanel wb={wb} />
          </div>

          <ExamplesSection wb={wb} />
          <footer className="page-footer">
            <span>FORM · 将灵感塑造成形</span>
            <span>单图中的遮挡与不可见结构需要人工确认</span>
          </footer>
        </main>
      </div>

      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button aria-label="关闭提示" onClick={() => setToast('')}>
            <X size={16} />
          </button>
        </div>
      )}
      <PanelModal wb={wb} />
    </div>
  );
}
