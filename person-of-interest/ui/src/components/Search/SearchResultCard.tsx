import type { Visit } from '../../types';

interface Props {
  visit: Visit;
  index: number;
}

const fmtTime = (ts: string) =>
  new Date(ts).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

const fmtDuration = (sec: number) => {
  const m = Math.floor(sec / 60);
  return m > 0 ? `${m} min` : `${sec}s`;
};

const VisitCard = ({ visit, index }: Props) => {
  const isActive = visit.exit_time === null;

  return (
    <div className={`bg-white rounded-xl border overflow-hidden ${isActive ? 'border-green-300 ring-1 ring-green-200' : 'border-gray-200'}`}>
      <div className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-intel-blue text-white text-xs flex items-center justify-center font-semibold">{index + 1}</span>
            <h3 className="text-sm font-medium text-intel-dark">{visit.date}</h3>
          </div>
          {isActive && <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-green-100 text-green-700 animate-pulse">IN STORE</span>}
        </div>

        {/* Time range */}
        <div className="flex items-center gap-2 text-xs text-intel-gray">
          <span>Entry: <span className="font-medium text-intel-dark">{fmtTime(visit.entry_time)}</span></span>
          <span>→</span>
          <span>Exit: <span className="font-medium text-intel-dark">{visit.exit_time ? fmtTime(visit.exit_time) : '—'}</span></span>
          {visit.duration_sec != null && (
            <>
              <span className="mx-1">·</span>
              <span className="font-medium text-intel-dark">{fmtDuration(visit.duration_sec)}</span>
            </>
          )}
        </div>

        {/* Camera path */}
        <div>
          <p className="text-[11px] text-intel-gray mb-1.5">Camera Path</p>
          <div className="flex flex-wrap items-center gap-1">
            {visit.cameras_visited.map((cam, i) => (
              <span key={`${cam}-${i}`} className="flex items-center gap-1">
                <span className="px-2 py-0.5 bg-gray-100 rounded text-[11px] font-medium text-intel-dark">{cam}</span>
                {i < visit.cameras_visited.length - 1 && <span className="text-intel-gray text-[10px]">→</span>}
              </span>
            ))}
          </div>
        </div>

        {/* Alert ID */}
        <p className="text-[10px] text-intel-gray">Alert: {visit.alert_id}</p>
      </div>
    </div>
  );
};

export default VisitCard;
