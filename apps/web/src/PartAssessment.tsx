export interface QualityDimension {
  key: string;
  label: string;
  status: 'passed' | 'warning' | 'blocked' | 'unverified';
  summary: string;
}

const labels = { passed: '检查通过', warning: '需要注意', blocked: '未通过', unverified: '待确认' };

export default function PartAssessment({ dimensions }: { dimensions?: QualityDimension[] }) {
  if (!dimensions?.length) return null;
  return (
    <div className="part-assessment-grid" aria-label="部件分项验收">
      {dimensions.map((dimension) => (
        <div key={dimension.key} className={'part-assessment ' + dimension.status}>
          <strong>{dimension.label}</strong>
          <span>{labels[dimension.status]}</span>
          <p>{dimension.summary}</p>
        </div>
      ))}
    </div>
  );
}
