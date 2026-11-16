import { api, statusLabels } from '../types';
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Box,
  ChevronRight,
  Cloud,
  History,
  Layers3,
  ShieldCheck,
  Sparkles,
  WandSparkles,
  X,
} from 'lucide-react';
import { routeNames } from './constants';
import type { Workbench } from './useWorkbench';

export default function PanelModal({ wb }: { wb: Workbench }) {
  const {
    config,
    samples,
    jobs,
    job,
    image,
    target,
    name,
    route,
    template,
    panel,
    setPanel,
    modelLoaded,
    openJob,
    showSample,
  } = wb;
  return (
    <>
      {panel && (
        <div className="modal-backdrop" onClick={() => setPanel(null)}>
          <section
            className={'modal ' + (panel === 'assets' ? 'wide-modal' : '')}
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <span className="eyebrow">FORM WORKSPACE</span>
                <h2 id="dialog-title">
                  {
                    {
                      history: '任务记录',
                      assets: '资产库',
                      help: '从第一件商品开始',
                      settings: '服务与工作空间',
                      report: '质量报告',
                    }[panel]
                  }
                </h2>
              </div>
              <button className="icon-button" aria-label="关闭窗口" onClick={() => setPanel(null)}>
                <X size={20} />
              </button>
            </div>
            {panel === 'history' && (
              <div className="history-list">
                {jobs.length ? (
                  jobs.map((task) => (
                    <button key={task.id} onClick={() => void openJob(task)}>
                      <span className="history-icon">
                        <Box size={20} />
                      </span>
                      <span>
                        <strong>{task.name}</strong>
                        <small>
                          {new Date(task.created_at).toLocaleString('zh-CN')} ·{' '}
                          {routeNames[task.request.route]}
                        </small>
                      </span>
                      <span className={'status-tag status-' + task.status}>
                        {statusLabels[task.status]}
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))
                ) : (
                  <div className="modal-empty">
                    <History size={32} />
                    <p>还没有任务，上传第一张参考图即可开始。</p>
                  </div>
                )}
              </div>
            )}
            {panel === 'assets' && (
              <>
                <p className="modal-description">
                  参考资产用于体验预览；你的生成资产会保存在本地任务记录中。
                </p>
                <div className="asset-grid">
                  {samples.map((item) => (
                    <button className="example-card" key={item.id} onClick={() => showSample(item)}>
                      <div className="example-image">
                        <img src={item.preview_url} alt={item.name} />
                        <span>参考资产</span>
                      </div>
                      <div className="example-caption">
                        <strong>{item.name}</strong>
                        <ArrowUpRight size={16} />
                      </div>
                    </button>
                  ))}
                </div>
                <h3 className="modal-subheading">已审核资产</h3>
                {jobs
                  .filter((task) => task.status === 'completed')
                  .map((task) => (
                    <button className="asset-job" key={task.id} onClick={() => void openJob(task)}>
                      <Box size={16} />
                      {task.name}
                      <ArrowRight size={15} />
                    </button>
                  ))}
                {!jobs.some((task) => task.status === 'completed') && (
                  <p className="muted">审核通过后，你的资产会显示在这里。</p>
                )}
              </>
            )}
            {panel === 'help' && (
              <div className="help-content">
                {[
                  [
                    '01',
                    '上传并选中商品',
                    '上传一张 JPG、PNG 或 WebP 图片，本地模型会自动找出柜子、花瓶、沙发、盆栽等候选，点击即可选择。必要时再修正框选或擦除背景。',
                  ],
                  [
                    '02',
                    '选择生成方式',
                    '本地自动生成无需密钥：提交后由本机 TripoSR 自动生成 GLB。对话看图建模保留用于人工协作；云端服务需要另行配置密钥。',
                  ],
                  [
                    '03',
                    '旋转查看与审核',
                    '查看正面、背面和侧面，确认部件、轮廓与材质。可直接下载 GLB；处理记录包另外保留图片与质量报告，供复查和返工。',
                  ],
                ].map(([number, title, description]) => (
                  <div className="help-step" key={number}>
                    <span>{number}</span>
                    <div>
                      <h3>{title}</h3>
                      <p>{description}</p>
                    </div>
                  </div>
                ))}
                <div className="notice">
                  <ShieldCheck size={18} />
                  <p>
                    单张图片无法保证恢复不可见结构与真实尺度。本地生成会分割主体、清理独立尺寸标注并检查输入风险；破碎掩码、像素不足或可能遮挡的任务会提示修正图片。遮挡补全和精确照片纹理尚未实现。
                  </p>
                </div>
              </div>
            )}
            {panel === 'settings' && (
              <div className="settings-content">
                <div className="service-row">
                  <span>
                    <ShieldCheck size={19} />
                    <strong>尺寸标注清理与输入检查</strong>
                  </span>
                  <span
                    className={config?.input_preparation?.available ? 'service-ready' : 'muted'}
                  >
                    {config?.input_preparation?.available
                      ? '本地已就绪 · 不补全遮挡'
                      : '待安装或实际运行验证'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Sparkles size={19} />
                    <strong>TripoSR 本地自动生成</strong>
                  </span>
                  <span className={config?.providers.local.available ? 'service-ready' : 'muted'}>
                    {config?.providers.local.available
                      ? '已就绪，无需密钥'
                      : '模型或运行环境待就绪'}
                  </span>
                </div>
                {config?.providers.local.device && (
                  <p className="muted">本地显卡：{config.providers.local.device}</p>
                )}
                <div className="service-row">
                  <span>
                    <Box size={19} />
                    <strong>Hunyuan3D-2mini 几何实验</strong>
                  </span>
                  <span
                    className={
                      config?.providers.local.engines?.['hunyuan-mini']?.available
                        ? 'service-ready'
                        : 'muted'
                    }
                  >
                    {config?.providers.local.engines?.['hunyuan-mini']?.available
                      ? '实际推理已验证 · 无纹理'
                      : '实际运行验证待完成'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Box size={19} />
                    <strong>对话看图建模</strong>
                  </span>
                  <span className="service-ready">可用</span>
                </div>
                <div className="service-row">
                  <span>
                    <WandSparkles size={19} />
                    <strong>本地目标识别</strong>
                  </span>
                  <span className={config?.detection.available ? 'service-ready' : 'muted'}>
                    {config?.detection.available ? '已就绪，无需密钥' : '模型未就绪'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Sparkles size={19} />
                    <strong>Meshy 图生 3D</strong>
                  </span>
                  <span className={config?.providers.meshy.available ? 'service-ready' : 'muted'}>
                    {config?.providers.meshy.available ? '密钥已配置，需实际账号联调' : '未配置'}
                  </span>
                </div>
                <div className="service-row">
                  <span>
                    <Layers3 size={19} />
                    <strong>SAM 2 目标精细分割</strong>
                  </span>
                  <span
                    className={config?.target_segmentation?.available ? 'service-ready' : 'muted'}
                  >
                    {config?.target_segmentation?.available
                      ? '本地已就绪 · 按目标框提取'
                      : '待安装或运行验证'}
                  </span>
                </div>
                <p>
                  在项目根目录的 <code>.env</code> 中设置 <code>MESHY_API_KEY</code>
                  ，然后重启后端。密钥保存在服务端，不进入浏览器。
                </p>
                <div className="notice">
                  <Cloud size={18} />
                  <p>
                    云端按供应商规则计费，当前适配器尚需真实账号验证。本地模式采用 SQLite
                    与本地文件，适合单人试验，请保持服务仅监听 127.0.0.1。
                  </p>
                </div>
                <p className="muted">
                  生成式遮挡补全：待接入
                  <br />
                  真实尺寸 AR：待验证
                  <br />
                  本地 API：
                  <a href="/docs" target="_blank" rel="noreferrer">
                    查看接口文档 <ArrowUpRight size={12} />
                  </a>
                </p>
              </div>
            )}
            {panel === 'report' &&
              (job?.report ? (
                <div className="report-content">
                  <div className="report-summary">
                    <ShieldCheck size={22} />
                    <div>
                      <strong>
                        {job.status === 'completed'
                          ? '人工审核已通过'
                          : '技术检查完成，外观需要审核'}
                      </strong>
                      <span>
                        {job.request.route === 'local'
                          ? job.request.local_engine === 'hunyuan-mini'
                            ? '结构来源：本机 Hunyuan3D-2mini；当前仅几何，不含纹理'
                            : '结构来源：本机 TripoSR 根据当前图片自动推理'
                          : job.request.route === 'assistant'
                            ? '结构来源：根据参考图进行独立 Blender 建模'
                            : job.request.route === 'template'
                              ? '结构来源：人工选择的参数模板'
                              : '结构来源：云端图片生成'}
                      </span>
                    </div>
                  </div>
                  <div className="report-rows">
                    <div>
                      <span>GLB 基础结构检查</span>
                      <strong>通过</strong>
                    </div>
                    <div>
                      <span>完整 glTF Validator</span>
                      <span>
                        {job.report.checks.full_gltf_validator === 'pass' ? '通过' : '未执行'}
                      </span>
                    </div>
                    <div>
                      <span>浏览器模型加载</span>
                      <span>{modelLoaded ? '当前页面已加载' : '待查看'}</span>
                    </div>
                    <div>
                      <span>外观审核</span>
                      <span>
                        {job.review_status === 'accepted'
                          ? '已通过'
                          : job.review_status === 'rejected'
                            ? '需修改'
                            : '待审核'}
                      </span>
                    </div>
                    <div>
                      <span>真实尺度 AR</span>
                      <span>未启用</span>
                    </div>
                  </div>
                  <h3>结果说明</h3>
                  <ul>
                    {job.report.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                  <a
                    className="button secondary"
                    href={`/api/jobs/${job.id}/files/quality_report.json`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <ArrowDownToLine size={15} />
                    下载完整质量报告
                  </a>
                </div>
              ) : (
                <div className="modal-empty">
                  <Box size={32} />
                  <p>模型完成后可查看检查报告。</p>
                </div>
              ))}
          </section>
        </div>
      )}
    </>
  );
}
