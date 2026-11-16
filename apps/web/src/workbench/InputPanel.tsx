import DetectedTargets from '../DetectedTargets';
import ImageEditor from '../ImageEditor';
import { api } from '../types';
import type { UploadedImage } from '../types';
import {
  ArrowRight,
  ArrowUpRight,
  Box,
  Check,
  ChevronDown,
  CircleHelp,
  Cloud,
  FileImage,
  ImagePlus,
  LoaderCircle,
  Plus,
  Sparkles,
  WandSparkles,
  Boxes,
} from 'lucide-react';
import { templateNames, colors } from './constants';
import type { Workbench } from './useWorkbench';

export default function InputPanel({ wb }: { wb: Workbench }) {
  const {
    partsPlanReview,
    setPartsPlanReview,
    partsReady,
    partsCategoryReady,
    config,
    job,
    image,
    inputReferences,
    setInputReferences,
    target,
    setTarget,
    strokes,
    setStrokes,
    name,
    setName,
    route,
    setRoute,
    removeBackground,
    setRemoveBackground,
    localEngine,
    setLocalEngine,
    localSegmentation,
    setLocalSegmentation,
    objectCategory,
    setObjectCategory,
    autoRetry,
    setAutoRetry,
    objects,
    setObjects,
    selectedObject,
    setSelectedObject,
    objectLabel,
    selectionTouched,
    template,
    setTemplate,
    width,
    setWidth,
    confirmed,
    setConfirmed,
    color,
    setColor,
    levels,
    setLevels,
    consent,
    setConsent,
    uploading,
    setUploading,
    submitting,
    dragging,
    setDragging,
    setPanel,
    modelEditing,
    fileInput,
    creationKey,
    busy,
    active,
    remoteNeedsAttention,
    assistantWaiting,
    localReady,
    notify,
    handleError,
    upload,
    generate,
    chooseObject,
    depth,
    setDepth,
    height,
    setHeight,
  } = wb;
  return (
    <>
      {!modelEditing && (
        <section className="card source-card">
          <div className="card-heading">
            <div>
              <span className="section-index">01</span>
              <h2>参考图片</h2>
            </div>
            <span className="tag">单件商品</span>
          </div>
          <input
            type="file"
            ref={fileInput}
            accept="image/jpeg,image/png,image/webp"
            className="hidden"
            data-testid="image-upload"
            onChange={(event) => void upload(event.target.files?.[0])}
          />
          {image ? (
            <>
              <div className="uploaded-heading">
                <div>
                  <FileImage size={16} />
                  <span title={image.name}>{image.name}</span>
                  <small>
                    {image.width} × {image.height}
                  </small>
                </div>
                <button disabled={busy} onClick={() => fileInput.current?.click()}>
                  更换图片
                </button>
              </div>
              <ImageEditor
                image={image}
                target={target}
                strokes={strokes}
                onTarget={(value) => {
                  setTarget(value);
                  selectionTouched.current = true;
                  setSelectedObject('');
                  creationKey.current = undefined;
                }}
                onStrokes={(value) => {
                  setStrokes(value);
                  selectionTouched.current = true;
                  creationKey.current = undefined;
                }}
                disabled={!!busy}
                objects={objects}
                onObject={chooseObject}
              />
              <DetectedTargets
                key={image.id}
                image={image}
                available={!!config?.detection.available}
                selected={selectedObject}
                autoPick={!selectionTouched.current && !job}
                onObjects={setObjects}
                onSelect={chooseObject}
              />
              {job?.segmented_url && (
                <div className="segmentation-preview">
                  <strong>SAM 2 目标分割结果</strong>
                  <div className="segmentation-images">
                    <a href={job.segmented_url} target="_blank" rel="noreferrer">
                      <img src={job.segmented_url} alt="目标主体精细分割结果" />
                      <span>主体提取 · 点击放大</span>
                    </a>
                    <a href={job.segmentation_overlay_url} target="_blank" rel="noreferrer">
                      <img src={job.segmentation_overlay_url} alt="目标分割掩码叠加图" />
                      <span>绿色保留 · 红色丢弃</span>
                    </a>
                  </div>
                  <p>
                    这是算法结果，不是真值标注。可检查靠背、扶手与细腿是否保留；不会补全遮挡部分。
                  </p>
                </div>
              )}
              {job?.input_quality && (
                <div
                  className={
                    'input-preparation ' +
                    (job.input_quality.status === 'blocked' ? 'input-blocked' : '')
                  }
                >
                  <strong>
                    {job.input_quality.status === 'blocked'
                      ? '输入需要修正，已停止建模'
                      : '输入清理与质量检查已完成'}
                  </strong>
                  <p>
                    {job.input_quality.removed_alpha_pixels > 0
                      ? '已清除与主体分离的尺寸标注。商品文字与主体结构保留。'
                      : '未发现可安全自动清除的独立尺寸文字。'}
                  </p>
                  {job.input_quality.reasons.map((reason) => (
                    <p key={reason.code}>{reason.message}</p>
                  ))}
                  {job.input_quality.warnings.map((warning) => (
                    <p key={warning}>{warning}</p>
                  ))}
                  <div className="segmentation-images">
                    <a href={job.cleaned_url} target="_blank" rel="noreferrer">
                      <img src={job.cleaned_url} alt="清理后的建模输入" />
                      <span>实际清理结果</span>
                    </a>
                    <a href={job.input_overlay_url} target="_blank" rel="noreferrer">
                      <img src={job.input_overlay_url} alt="文字和遮挡检查标记" />
                      <span>绿：清理 · 橙：保留文字 · 红：遮挡候选</span>
                    </a>
                  </div>
                  <p>检查通过只表示可以继续实验，不代表外观合格。遮挡部分尚未补全。</p>
                  <a href={job.input_quality_url} target="_blank" rel="noreferrer">
                    查看输入检查记录
                  </a>
                </div>
              )}
            </>
          ) : (
            <button
              className={'upload-zone ' + (dragging ? 'dragging' : '')}
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                void upload(event.dataTransfer.files[0]);
              }}
            >
              <span className="upload-illustration">
                <span className="floating-square" />
                <span className="photo-symbol">
                  <ImagePlus size={36} strokeWidth={1.4} />
                </span>
                <span className="upload-mini">
                  {uploading ? <LoaderCircle className="spin" size={17} /> : <Plus size={17} />}
                </span>
              </span>
              <strong>{uploading ? '正在保存参考图片…' : '点击上传，或把图片拖到这里'}</strong>
              <span>白底商品图或场景图均可</span>
              <small>JPG、PNG、WebP · 最大 12 MB</small>
            </button>
          )}
          <div className="source-tip">
            <span className="tip-dot" />
            <span>尽量选用主体完整、清晰且遮挡较少的图片</span>
            <CircleHelp size={13} />
          </div>
          {image && !job && (
            <details className="input-references">
              <summary>补充参考视图（可选）</summary>
              <p>
                当前上传的主图用于生成；侧面、背面等补充图只用于验收对照，当前本地模型不做多视图融合。
              </p>
              <input
                aria-label="建模补充视图"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                disabled={busy}
                onChange={async (event) => {
                  const files = Array.from(event.target.files || []);
                  if (inputReferences.length + files.length > 8) return notify('最多 8 张补充图');
                  setUploading(true);
                  try {
                    const added: UploadedImage[] = [];
                    for (const file of files) {
                      const body = new FormData();
                      body.append('file', file);
                      added.push(await api<UploadedImage>('/api/images', { method: 'POST', body }));
                    }
                    setInputReferences((old) => [...old, ...added]);
                    creationKey.current = undefined;
                  } catch (error) {
                    handleError(error);
                  } finally {
                    setUploading(false);
                  }
                }}
              />
              <div className="reference-thumbnails">
                {inputReferences.map((ref) => (
                  <button
                    key={ref.id}
                    onClick={() => setInputReferences((old) => old.filter((v) => v.id !== ref.id))}
                    title="移除此补充视图"
                  >
                    <img src={ref.preview_url} alt="待保存的补充视图" />
                    移除
                  </button>
                ))}
              </div>
            </details>
          )}

          <fieldset disabled={!!busy} className="generation-settings">
            <label className="field-label" htmlFor="task-name">
              商品名称 <span>可选</span>
            </label>
            <input
              id="task-name"
              className="text-input"
              placeholder="为这件商品起个名字"
              maxLength={100}
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                creationKey.current = undefined;
              }}
            />
            <div className="setting-title">
              <label className="field-label">生成方式</label>
              <button type="button" onClick={() => setPanel('settings')}>
                服务状态 <ArrowUpRight size={11} />
              </button>
            </div>
            <div className="route-options">
              <button
                disabled={!partsReady}
                title={
                  partsReady
                    ? ''
                    : '缺少：' + (config?.providers.parts_first?.missing ?? []).join('、')
                }
                className={'route-option parts-route ' + (route === 'parts_first' ? 'chosen' : '')}
                onClick={() => {
                  setRoute('parts_first');
                  creationKey.current = undefined;
                }}
              >
                <Boxes size={18} />
                <span>
                  <strong>部件优先生成</strong>
                  <small>{partsReady ? 'PartCrafter · 可编辑部件' : '部件环境待就绪'}</small>
                </span>
                <i>{route === 'parts_first' && <Check size={10} />}</i>
              </button>
              <button
                disabled={!config?.providers.local.available}
                className={'route-option local-route ' + (route === 'local' ? 'chosen' : '')}
                onClick={() => {
                  setRoute('local');
                  creationKey.current = undefined;
                }}
              >
                <Sparkles size={18} />
                <span>
                  <strong>本地自动生成</strong>
                  <small>
                    {config?.providers.local.available
                      ? localEngine === 'hunyuan-mini'
                        ? 'Hunyuan · 仅几何'
                        : 'TripoSR · 无需密钥'
                      : '本地模型待就绪'}
                  </small>
                </span>
                <i>{route === 'local' && <Check size={10} />}</i>
              </button>
              <button
                className={
                  'route-option assistant-route ' + (route === 'assistant' ? 'chosen' : '')
                }
                onClick={() => {
                  setRoute('assistant');
                  creationKey.current = undefined;
                }}
              >
                <WandSparkles size={18} />
                <span>
                  <strong>对话看图建模</strong>
                  <small>对话协作 · 无需密钥</small>
                </span>
                <i>{route === 'assistant' && <Check size={10} />}</i>
              </button>
              <button
                className={'route-option ' + (route === 'template' ? 'chosen' : '')}
                onClick={() => {
                  setRoute('template');
                  creationKey.current = undefined;
                }}
              >
                <Box size={18} />
                <span>
                  <strong>手动结构工具</strong>
                  <small>仅按参数搭建</small>
                </span>
                <i>{route === 'template' && <Check size={10} />}</i>
              </button>
              <button
                disabled={!config?.providers.meshy.available}
                title={!config?.providers.meshy.available ? '请先在服务端配置 Meshy API 密钥' : ''}
                className={'route-option ' + (route === 'meshy' ? 'chosen' : '')}
                onClick={() => {
                  setRoute('meshy');
                  creationKey.current = undefined;
                }}
              >
                <Sparkles size={18} />
                <span>
                  <strong>云端图生 3D</strong>
                  <small>
                    {config?.providers.meshy.available ? '云端生成 · 按服务计费' : '待配置云端服务'}
                  </small>
                </span>
                <i>{route === 'meshy' && <Check size={10} />}</i>
              </button>
            </div>
            {route === 'template' ? (
              <>
                <div className="template-row">
                  <label className="field-label" htmlFor="template">
                    结构模板
                  </label>
                  <div className="select-wrap">
                    <select
                      id="template"
                      value={template}
                      onChange={(event) => {
                        setTemplate(event.target.value);
                        creationKey.current = undefined;
                      }}
                    >
                      {Object.entries(templateNames).map(([key, title]) => (
                        <option key={key} value={key}>
                          {title}
                        </option>
                      ))}
                    </select>
                    <ChevronDown size={13} />
                  </div>
                </div>
                <div className="dimension-label">
                  <label className="field-label">外形尺寸</label>
                  <span>单位 cm</span>
                </div>
                <div className="dimension-inputs">
                  {[
                    ['宽', width, setWidth],
                    ['深', depth, setDepth],
                    ['高', height, setHeight],
                  ].map(([label, value, setter]) => (
                    <label key={String(label)}>
                      <span>{String(label)}</span>
                      <input
                        aria-label={`${label}度（厘米）`}
                        type="number"
                        min={10}
                        max={500}
                        step={1}
                        value={Number(value)}
                        onChange={(event) => {
                          (setter as (v: number) => void)(Number(event.target.value));
                          creationKey.current = undefined;
                        }}
                      />
                    </label>
                  ))}
                </div>
                <div className="finish-row">
                  <div className="color-options">
                    <span>底色</span>
                    {colors.map((option) => (
                      <button
                        key={option}
                        style={{ background: option }}
                        className={color === option ? 'selected' : ''}
                        aria-label={'选择颜色 ' + option}
                        title={option}
                        onClick={() => {
                          setColor(option);
                          creationKey.current = undefined;
                        }}
                      >
                        {color === option && (
                          <Check size={11} color={option === '#f3f0e9' ? '#34343f' : 'white'} />
                        )}
                      </button>
                    ))}
                  </div>
                  {template === 'shelf' && (
                    <label className="levels-control">
                      层数{' '}
                      <select
                        aria-label="层数"
                        value={levels}
                        onChange={(event) => {
                          setLevels(Number(event.target.value));
                          creationKey.current = undefined;
                        }}
                      >
                        {[2, 3, 4, 5, 6].map((value) => (
                          <option key={value}>{value}</option>
                        ))}
                      </select>
                    </label>
                  )}
                </div>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => {
                      setConfirmed(event.target.checked);
                      creationKey.current = undefined;
                    }}
                  />
                  <span>以上尺寸已对照实物或厂家资料确认</span>
                </label>
                <p className="method-note">
                  按所选模板与尺寸构建结构；当前需人工选择模板，图片用于参照。
                </p>
              </>
            ) : route === 'local' ? (
              <div className="assistant-note local-note">
                <strong>
                  {localReady
                    ? '提交后自动生成，完成后直接在右侧查看。'
                    : '所选本地模型尚未完成运行验证。'}
                </strong>
                <div className="template-row">
                  <label className="field-label" htmlFor="local-engine">
                    本地模型
                  </label>
                  <div className="select-wrap">
                    <select
                      id="local-engine"
                      value={localEngine}
                      onChange={(event) => {
                        setLocalEngine(event.target.value as 'triposr' | 'hunyuan-mini');
                        creationKey.current = undefined;
                      }}
                    >
                      <option value="triposr" disabled={!config?.providers.local.available}>
                        TripoSR · 快速彩色
                      </option>
                      <option
                        value="hunyuan-mini"
                        disabled={!config?.providers.local.engines?.['hunyuan-mini']?.available}
                      >
                        Hunyuan3D-2mini · 几何实验
                      </option>
                    </select>
                    <ChevronDown size={13} />
                  </div>
                </div>
                <p>
                  {localEngine === 'hunyuan-mini'
                    ? '本轮只生成形状，使用中性灰材质，不包含商品纹理。生成完成后仍须检查关键结构、背面和尺寸。'
                    : '推荐单件、完整、背景干净的商品图。图片在本机处理，输出带颜色的 GLB，背面与尺寸需要审核。'}
                </p>
                <div className="template-row">
                  <label className="field-label" htmlFor="object-category">
                    目标品类
                  </label>
                  <select
                    id="object-category"
                    value={objectCategory}
                    onChange={(event) => {
                      setObjectCategory(event.target.value);
                      creationKey.current = undefined;
                    }}
                  >
                    <option value="">跟随识别 / 不确定</option>
                    <option value="cabinet">柜子 / 书柜</option>
                    <option value="table">桌子</option>
                    <option value="sofa">沙发 / 扶手椅</option>
                    <option value="chair">椅子</option>
                    <option value="vase">花瓶</option>
                    <option value="plant">盆栽</option>
                    <option value="lamp">灯具</option>
                    <option value="other">其他 / 薄结构</option>
                  </select>
                </div>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={autoRetry}
                    onChange={(event) => {
                      setAutoRetry(event.target.checked);
                      creationKey.current = undefined;
                    }}
                  />
                  <span>几何异常时最多换一个本地模型重试</span>
                </label>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={removeBackground}
                    onChange={(event) => {
                      setRemoveBackground(event.target.checked);
                      creationKey.current = undefined;
                    }}
                  />
                  <span>生成前自动去背景（已抠好的透明图可关闭）</span>
                </label>
                {removeBackground && (
                  <>
                    <div className="template-row">
                      <label className="field-label" htmlFor="local-segmentation">
                        分割策略
                      </label>
                      <div className="select-wrap">
                        <select
                          id="local-segmentation"
                          value={localSegmentation}
                          onChange={(event) => {
                            setLocalSegmentation(event.target.value as 'auto' | 'sam2' | 'basic');
                            creationKey.current = undefined;
                          }}
                        >
                          <option value="auto">自动选择</option>
                          <option value="sam2" disabled={!config?.target_segmentation?.available}>
                            SAM 2 · 目标框分割
                          </option>
                          <option value="basic">基础去背景</option>
                        </select>
                        <ChevronDown size={13} />
                      </div>
                    </div>
                    <p>
                      {config?.target_segmentation?.available
                        ? '自动模式：复杂背景按目标框使用 SAM 2；白底和透明图保留原有处理。分割完成后可查看掩码叠加图。'
                        : 'SAM 2 尚未就绪，自动模式暂用基础去背景；复杂背景需要检查主体是否完整。'}
                    </p>
                  </>
                )}
              </div>
            ) : route === 'parts_first' ? (
              <div className="assistant-note parts-first-note">
                <strong>先在原图中识别部件，再按部件生成并装配。</strong>
                <p>
                  流程：识别坐垫、靠枕、桌面、桌腿、柜门等部件 → PartCrafter 按部件联合生成 →
                  检查闭合与原图对应 → 输出带部件身份的
                  GLB。任一阶段证据不足会停下说明原因，不会发布不完整的装配。
                </p>
                <div className="template-row">
                  <label className="field-label" htmlFor="parts-category">
                    家具类别
                  </label>
                  <select
                    id="parts-category"
                    value={partsCategoryReady ? objectCategory : ''}
                    onChange={(event) => {
                      setObjectCategory(event.target.value);
                      creationKey.current = undefined;
                    }}
                  >
                    <option value="">请选择</option>
                    <option value="sofa">沙发 / 扶手椅</option>
                    <option value="chair">椅子</option>
                    <option value="table">桌子</option>
                    <option value="cabinet">柜子 / 书柜</option>
                  </select>
                </div>
                <label className="checkbox-label parts-review-toggle">
                  <input
                    type="checkbox"
                    checked={partsPlanReview}
                    onChange={(event) => {
                      setPartsPlanReview(event.target.checked);
                      creationKey.current = undefined;
                    }}
                  />
                  <span>识别完成后先让我确认部件（推荐）</span>
                </label>
                <span>
                  {partsReady
                    ? '仅几何、无纹理；最多 16 个部件；尺寸与隐藏结构未验证'
                    : '环境未就绪，缺少：' +
                      (config?.providers.parts_first?.missing ?? []).join('、')}
                </span>
              </div>
            ) : route === 'assistant' ? (
              <div className="assistant-note">
                <strong>先提交图片，再在当前对话中让我建模。</strong>
                <p>
                  我会根据选中的商品分析结构、编写模型并导出
                  GLB。完成后，模型会出现在右侧。当前需要对话协作，网页尚不能无人值守地调用我的能力。
                </p>
                <span>
                  {objectLabel
                    ? '当前物件：' + objectLabel
                    : '可提交完整商品图，也可选择已识别的物件'}
                </span>
              </div>
            ) : (
              <div className="cloud-consent">
                <p>
                  <Cloud size={15} /> 选区与擦除结果将作为云端生成输入。
                </p>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(event) => {
                      setConsent(event.target.checked);
                      creationKey.current = undefined;
                    }}
                  />
                  <span>
                    同意将处理后的图片发送给
                    Meshy，并由已配置账号承担供应商费用。每次仅提交一个候选。
                  </span>
                </label>
                <small>
                  提交状态不明确时暂停处理，不自动重复付费生成。实际费用请查看供应商账单。
                </small>
              </div>
            )}
          </fieldset>
          <div className="generate-footer">
            <button
              className="button primary generate-button"
              disabled={
                !image ||
                !!busy ||
                remoteNeedsAttention ||
                assistantWaiting ||
                (route === 'local' && !localReady) ||
                (route === 'parts_first' && (!partsReady || !partsCategoryReady)) ||
                (route === 'meshy' && !consent)
              }
              onClick={() => void generate()}
            >
              {busy ? <LoaderCircle size={17} className="spin" /> : <WandSparkles size={17} />}
              {submitting
                ? '正在创建任务'
                : active
                  ? '正在生成模型'
                  : assistantWaiting
                    ? '等待对话建模'
                    : remoteNeedsAttention
                      ? '请先核对云端任务'
                      : job?.model_url
                        ? '生成新的候选'
                        : route === 'assistant'
                          ? '提交看图建模'
                          : '开始生成'}
              {!busy && <ArrowRight size={16} />}
            </button>
            <span>
              {route === 'parts_first'
                ? '本机按部件生成 · 无需密钥'
                : route === 'assistant'
                  ? '无需密钥 · 在当前对话中继续处理'
                  : route === 'local'
                    ? '本机自动处理 · 无需密钥'
                    : route === 'template'
                      ? '本地处理，无模型 API 费用'
                      : '第三方处理，按供应商规则计费'}
            </span>
          </div>
        </section>
      )}
    </>
  );
}
