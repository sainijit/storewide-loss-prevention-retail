import { useState } from 'react';
import type { HistoryResult } from '../../types';
import { mockHistoryResult } from '../../mockData';
import VisitCard from './SearchResultCard';

const SearchPanel = () => {
  const [queryImage, setQueryImage] = useState<string | null>(null);
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [result, setResult] = useState<HistoryResult | null>(null);
  const [searched, setSearched] = useState(false);

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = () => setQueryImage(reader.result as string);
      reader.readAsDataURL(file);
    }
  };

  const handleSearch = () => {
    // In production: POST query image + time range to backend
    setResult(mockHistoryResult);
    setSearched(true);
  };

  const handleReset = () => {
    setQueryImage(null);
    setStartTime('');
    setEndTime('');
    setResult(null);
    setSearched(false);
  };

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 bg-white border-r border-gray-200 p-4 space-y-5 overflow-y-auto">
        <h3 className="text-sm font-semibold text-intel-dark">Search Parameters</h3>

        {/* Query image */}
        <div className="space-y-2">
          <span className="text-xs font-medium text-intel-gray">Query Image</span>
          {queryImage ? (
            <div className="relative group">
              <img src={queryImage} alt="Query" className="w-full aspect-square object-cover rounded-lg border border-gray-200" />
              <button
                onClick={() => setQueryImage(null)}
                className="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/60 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              >
                ×
              </button>
            </div>
          ) : (
            <label className="flex flex-col items-center justify-center h-32 border-2 border-dashed border-gray-300 rounded-lg cursor-pointer hover:border-intel-blue transition-colors">
              <span className="text-2xl text-intel-gray">📷</span>
              <span className="text-xs text-intel-gray mt-1">Upload Image</span>
              <input type="file" accept="image/*" onChange={handleUpload} className="hidden" />
            </label>
          )}
        </div>

        {/* Time range */}
        <label className="block">
          <span className="text-xs font-medium text-intel-gray">Start Time</span>
          <input
            type="datetime-local"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs focus:border-intel-blue focus:ring-1 focus:ring-intel-blue outline-none"
          />
        </label>

        <label className="block">
          <span className="text-xs font-medium text-intel-gray">End Time</span>
          <input
            type="datetime-local"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs focus:border-intel-blue focus:ring-1 focus:ring-intel-blue outline-none"
          />
        </label>

        <div className="space-y-2 pt-2">
          <button
            onClick={handleSearch}
            disabled={!queryImage}
            className="w-full px-4 py-2 text-sm font-medium text-white bg-intel-blue rounded-lg hover:bg-intel-blue-dark transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Search
          </button>
          <button
            onClick={handleReset}
            className="w-full px-4 py-2 text-sm font-medium text-intel-gray bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
          >
            Reset
          </button>
        </div>
      </aside>

      {/* Results */}
      <div className="flex-1 p-6 space-y-4 overflow-y-auto">
        <div>
          <h2 className="text-xl font-display font-medium text-intel-dark">Historical Search</h2>
          <p className="text-sm text-intel-gray mt-1">
            {searched && result
              ? `${result.total_visits} visit${result.total_visits !== 1 ? 's' : ''} found for ${result.poi_id}`
              : 'Upload a reference image and search for historical appearances'}
          </p>
        </div>

        {/* Search stats */}
        {result && (
          <div className="flex gap-3">
            <div className="bg-blue-50 rounded-lg px-4 py-2 text-center">
              <p className="text-lg font-semibold text-intel-blue">{result.total_visits}</p>
              <p className="text-[11px] text-intel-gray">Visits</p>
            </div>
            <div className="bg-blue-50 rounded-lg px-4 py-2 text-center">
              <p className="text-lg font-semibold text-intel-blue">{result.search_stats.vectors_searched.toLocaleString()}</p>
              <p className="text-[11px] text-intel-gray">Vectors Searched</p>
            </div>
            <div className="bg-blue-50 rounded-lg px-4 py-2 text-center">
              <p className="text-lg font-semibold text-intel-blue">{result.search_stats.query_latency_ms} ms</p>
              <p className="text-[11px] text-intel-gray">Query Latency</p>
            </div>
            <div className="bg-gray-50 rounded-lg px-4 py-2 text-center text-[11px] text-intel-gray">
              <p className="font-medium text-intel-dark text-xs">Range</p>
              <p>{new Date(result.query_range.start).toLocaleDateString()} — {new Date(result.query_range.end).toLocaleDateString()}</p>
            </div>
          </div>
        )}

        {/* Visit list */}
        {result && result.visits.length > 0 ? (
          <div className="space-y-3">
            {result.visits.map((visit, i) => (
              <VisitCard key={visit.alert_id} visit={visit} index={i} />
            ))}
          </div>
        ) : searched ? (
          <div className="text-center py-20 text-intel-gray">
            <p className="text-lg">No appearances found</p>
            <p className="text-sm mt-1">Try a different image or expand the time range</p>
          </div>
        ) : (
          <div className="text-center py-20 text-intel-gray">
            <p className="text-lg">Upload a query image to begin</p>
            <p className="text-sm mt-1">Historical visit records will appear here</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default SearchPanel;
