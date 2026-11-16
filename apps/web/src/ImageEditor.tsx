import { useEffect, useRef, useState } from 'react';
import { Crop, Eraser, Undo2, RotateCcw, MousePointer2, ScanSearch } from 'lucide-react';
import type { DetectedObject, Point, Stroke, Target, UploadedImage } from './types';

interface Props {
  image: UploadedImage;
  target: Target;
  strokes: Stroke[];
  onTarget: (target: Target) => void;
  onStrokes: (strokes: Stroke[]) => void;
  disabled: boolean;
  objects: DetectedObject[];
  onObject: (object: DetectedObject) => void;
}

export default function ImageEditor({
  image,
  target,
  strokes,
  onTarget,
  onStrokes,
  disabled,
  objects,
  onObject,
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const picture = useRef<HTMLImageElement>();
  const gesture = useRef<{ start: Point; points: Point[]; mode: string }>();
  const [mode, setMode] = useState('auto');
  const [brush, setBrush] = useState(0.035);
  const [draft, setDraft] = useState<Stroke | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    setReady(false);
    setError(false);
    const source = new Image();
    let disposed = false;
    source.onload = () => {
      if (!disposed) {
        picture.current = source;
        setReady(true);
      }
    };
    source.onerror = () => {
      if (!disposed) setError(true);
    };
    source.src = image.preview_url;
    return () => {
      disposed = true;
    };
  }, [image.preview_url]);

  useEffect(() => {
    const element = canvas.current,
      source = picture.current;
    if (!element || !source || !ready) return;
    const ratio = Math.min(1, 1400 / source.width);
    const w = (element.width = Math.round(source.width * ratio)),
      h = (element.height = Math.round(source.height * ratio));
    const ctx = element.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(source, 0, 0, w, h);
    ctx.fillStyle = '#24253b66';
    ctx.beginPath();
    ctx.rect(0, 0, w, h);
    ctx.rect(target.x * w, target.y * h, target.width * w, target.height * h);
    ctx.fill('evenodd');
    ctx.strokeStyle = '#7960e9';
    ctx.lineWidth = 3;
    ctx.setLineDash([9, 5]);
    ctx.strokeRect(target.x * w + 1, target.y * h + 1, target.width * w - 2, target.height * h - 2);
    ctx.setLineDash([]);
    ctx.font = `${Math.max(13, Math.round(w * 0.018))}px "Microsoft YaHei", sans-serif`;
    for (const object of objects) {
      const box = object.target;
      const x = box.x * w,
        y = box.y * h,
        bw = box.width * w,
        bh = box.height * h;
      ctx.strokeStyle = '#9880d8';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, bw, bh);
      const label = object.label + (object.score < 0.4 ? '？' : '');
      const textWidth = ctx.measureText(label).width;
      const textHeight = Math.max(19, Math.round(w * 0.025));
      ctx.fillStyle = '#7860d9';
      ctx.fillRect(x, Math.max(0, y - textHeight), textWidth + 12, textHeight);
      ctx.fillStyle = '#fff';
      ctx.fillText(label, x + 6, Math.max(textHeight - 4, y - 5));
    }
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(236, 87, 124, .66)';
    ctx.fillStyle = ctx.strokeStyle;
    for (const stroke of [...strokes, ...(draft ? [draft] : [])]) {
      ctx.lineWidth = stroke.radius * Math.min(w, h) * 2;
      ctx.beginPath();
      stroke.points.forEach((point, i) =>
        i ? ctx.lineTo(point.x * w, point.y * h) : ctx.moveTo(point.x * w, point.y * h),
      );
      ctx.stroke();
      for (const point of [stroke.points[0], stroke.points[stroke.points.length - 1]]) {
        ctx.beginPath();
        ctx.arc(point.x * w, point.y * h, ctx.lineWidth / 2, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }, [target, strokes, draft, ready, objects]);

  function point(event: React.PointerEvent): Point {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  }

  return (
    <div className="image-editor">
      <div className="editor-toolbar">
        <div className="segmented">
          <button
            disabled={disabled}
            className={mode === 'auto' ? 'active' : ''}
            onClick={() => setMode('auto')}
          >
            <ScanSearch size={14} />
            自动目标
          </button>
          <button
            disabled={disabled}
            className={mode === 'select' ? 'active' : ''}
            onClick={() => setMode('select')}
          >
            <Crop size={14} /> 框选目标
          </button>
          <button
            disabled={disabled}
            className={mode === 'erase' ? 'active' : ''}
            onClick={() => setMode('erase')}
          >
            <Eraser size={14} /> 擦除背景
          </button>
        </div>
        <button
          className="icon-button"
          disabled={disabled || !strokes.length}
          aria-label="撤销擦除"
          title="撤销擦除"
          onClick={() => onStrokes(strokes.slice(0, -1))}
        >
          <Undo2 size={15} />
        </button>
        <button
          className="icon-button"
          disabled={disabled}
          aria-label="重置选区和擦除"
          title="重置选区和擦除"
          onClick={() => {
            onTarget({ x: 0, y: 0, width: 1, height: 1 });
            onStrokes([]);
          }}
        >
          <RotateCcw size={15} />
        </button>
      </div>
      <div className={'editor-stage ' + (mode === 'erase' ? 'erase-cursor' : '')}>
        {error ? (
          <span className="muted">图片加载失败，请重新上传</span>
        ) : (
          <canvas
            ref={canvas}
            style={{ opacity: ready ? 1 : 0 }}
            aria-label="商品图片编辑区域"
            onPointerDown={(event) => {
              if (disabled || !ready) return;
              const p = point(event);
              if (mode === 'auto') {
                const hit = [...objects]
                  .filter(
                    (object) =>
                      p.x >= object.target.x &&
                      p.x <= object.target.x + object.target.width &&
                      p.y >= object.target.y &&
                      p.y <= object.target.y + object.target.height,
                  )
                  .sort(
                    (a, b) => a.target.width * a.target.height - b.target.width * b.target.height,
                  )[0];
                if (hit) onObject(hit);
                return;
              }
              gesture.current = { start: p, points: [p], mode };
              event.currentTarget.setPointerCapture(event.pointerId);
              if (mode === 'erase') setDraft({ points: [p], radius: brush });
            }}
            onPointerMove={(event) => {
              const g = gesture.current;
              if (!g) return;
              const p = point(event);
              if (g.mode === 'select') {
                const w = Math.abs(p.x - g.start.x),
                  h = Math.abs(p.y - g.start.y);
                if (w > 0.005 && h > 0.005)
                  onTarget({
                    x: Math.min(p.x, g.start.x),
                    y: Math.min(p.y, g.start.y),
                    width: w,
                    height: h,
                  });
              } else if (g.points.length < 1900) {
                g.points.push(p);
                setDraft({ points: [...g.points], radius: brush });
              }
            }}
            onPointerUp={() => {
              const g = gesture.current;
              if (g?.mode === 'erase' && strokes.length < 200)
                onStrokes([...strokes, { points: g.points, radius: brush }]);
              gesture.current = undefined;
              setDraft(null);
            }}
            onPointerCancel={() => {
              gesture.current = undefined;
              setDraft(null);
            }}
          />
        )}
      </div>
      <div className="editor-caption">
        <span>
          <MousePointer2 size={13} />{' '}
          {mode === 'erase'
            ? '粉色区域将在生成前移除，原图保留'
            : mode === 'auto'
              ? '点击已识别物件；需要修正时切换框选目标'
              : '拖动框选一件商品，保留完整轮廓'}
        </span>
        {mode === 'erase' && (
          <input
            aria-label="擦除笔刷大小"
            type="range"
            min="0.008"
            max="0.09"
            step="0.002"
            value={brush}
            onChange={(event) => setBrush(Number(event.target.value))}
          />
        )}
      </div>
    </div>
  );
}
