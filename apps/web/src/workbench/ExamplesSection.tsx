import { ArrowRight, ArrowUpRight, Box } from 'lucide-react';
import type { Workbench } from './useWorkbench';

export default function ExamplesSection({ wb }: { wb: Workbench }) {
  const { samples, sample, image, name, setPanel, modelEditing, showSample } = wb;
  return (
    <>
      {!modelEditing && (
        <section className="examples-section">
          <div className="examples-heading">
            <div>
              <h2>看看不同材质的可能</h2>
              <span>已有参考资产，体验模型的不同角度</span>
            </div>
            <button onClick={() => setPanel('assets')}>
              浏览资产库 <ArrowRight size={14} />
            </button>
          </div>
          <div className="examples-grid">
            {samples.map((item) => (
              <button
                key={item.id}
                className={
                  'example-card ' + (!image && sample?.id === item.id ? 'example-selected' : '')
                }
                onClick={() => showSample(item)}
              >
                <div className="example-image">
                  <img loading="lazy" src={item.preview_url} alt={item.name} />
                  <span>参考资产</span>
                  <i>
                    <ArrowUpRight size={16} />
                  </i>
                </div>
                <div className="example-caption">
                  <div>
                    <strong>{item.name}</strong>
                    <span>{item.material}</span>
                  </div>
                  <Box size={16} />
                </div>
              </button>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
