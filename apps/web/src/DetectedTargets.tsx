import { useEffect, useRef, useState } from 'react';
import { ScanSearch, LoaderCircle, RotateCcw } from 'lucide-react';
import { api, post } from './types';
import type { DetectedObject, DetectionResult, UploadedImage } from './types';

interface Props {
  image: UploadedImage;
  available: boolean;
  selected: string;
  autoPick: boolean;
  onObjects: (objects: DetectedObject[]) => void;
  onSelect: (object: DetectedObject) => void;
}

export default function DetectedTargets(props: Props) {
  const [result, setResult] = useState<DetectionResult | undefined>(props.image.analysis);
  const [error, setError] = useState('');
  const callbacks = useRef(props);
  callbacks.current = props;
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!props.available) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    function accept(image: UploadedImage) {
      if (stopped) return;
      const analysis = image.analysis;
      setResult(analysis);
      if (analysis?.status === 'completed') {
        callbacks.current.onObjects(analysis.objects);
        if (callbacks.current.autoPick && analysis.objects.length) {
          const priority = analysis.objects.filter((object) =>
            ['cabinet', 'sofa', 'table', 'chair'].includes(object.category),
          );
          const primary = [...(priority.length ? priority : analysis.objects)].sort(
            (a, b) => b.target.width * b.target.height - a.target.width * a.target.height,
          )[0];
          callbacks.current.onSelect(primary);
        }
      } else if (analysis?.status === 'failed') {
        setError(analysis.error || '识别暂时失败，可以重新识别或手工框选');
      } else {
        timer = setTimeout(() => {
          void api<UploadedImage>('/api/images/' + props.image.id)
            .then(accept)
            .catch(fail);
        }, 1500);
      }
    }
    function fail(reason: unknown) {
      if (!stopped) setError(reason instanceof Error ? reason.message : '本地识别暂时不可用');
    }
    setError('');
    if (props.image.analysis?.status === 'completed') accept(props.image);
    else {
      setResult({ status: 'queued', objects: [] });
      void post<UploadedImage>(`/api/images/${props.image.id}/analysis`).then(accept).catch(fail);
    }
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [props.image.id, props.available, attempt]);

  return (
    <div className="detected-targets">
      <div className="detection-heading">
        <span>
          <ScanSearch size={14} />
          自动识别目标
        </span>
        <small>本地处理 · 无需密钥</small>
      </div>
      {!props.available ? (
        <p>本地识别模型尚未准备好，暂可手工框选。</p>
      ) : error ? (
        <div className="detection-error">
          <span>{error}</span>
          <button aria-label="重新识别" onClick={() => setAttempt(attempt + 1)}>
            <RotateCcw size={13} />
            重试
          </button>
        </div>
      ) : !result || ['queued', 'running'].includes(result.status) ? (
        <div className="detection-running">
          <LoaderCircle className="spin" size={14} />
          <span>正在识别柜子、花瓶、沙发、盆栽等物件…</span>
        </div>
      ) : result.objects.length ? (
        <>
          <div className="object-chips">
            {result.objects.map((object) => (
              <button
                className={props.selected === object.id ? 'active' : ''}
                key={object.id}
                onClick={() => callbacks.current.onSelect(object)}
                title={'检测分数 ' + object.score}
              >
                <span>
                  {object.label}
                  {object.score < 0.4 ? '？' : ''}
                </span>
                <small>{Math.round(object.score * 100)}%</small>
              </button>
            ))}
          </div>
          <p>
            已识别 {result.objects.length}{' '}
            个候选，点击标签或图片里的框切换目标。带“？”的低分标签需要确认，特殊造型可能识别错误。
          </p>
        </>
      ) : (
        <p>未找到可靠目标。特殊造型可直接提交整图，或切换手工框选。</p>
      )}
    </div>
  );
}
