import { useState } from 'react';
import type { POI } from '../../types';
import { mockPOIs } from '../../mockData';
import POICard from './POICard';
import UploadModal from './UploadModal';
import POIDetailModal from './POIDetailModal';
import ImagePreviewModal from '../common/ImagePreviewModal';

const POIManagement = () => {
  const [pois, setPois] = useState<POI[]>(mockPOIs);
  const [showUpload, setShowUpload] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [detailPoi, setDetailPoi] = useState<POI | null>(null);

  const handleDelete = (id: string) => {
    setPois((prev) => prev.filter((p) => p.poi_id !== id));
  };

  const handleSave = ({ notes, severity, files }: { notes: string; severity: 'low' | 'medium' | 'high'; files: File[] }) => {
    if (files.length === 0) return;
    const poiNum = pois.length + 1;
    const poiId = `poi-${String(poiNum).padStart(3, '0')}`;

    const newPoi: POI = {
      event_type: 'poi_enrollment',
      timestamp: new Date().toISOString(),
      poi_id: poiId,
      enrolled_by: 'operator-ui',
      severity,
      notes: notes || '',
      reference_images: files.map((f, i) => ({
        source: 'uploaded_image',
        embedding_id: `emb-${poiId}-ref-${String(i + 1).padStart(2, '0')}`,
        vector_dim: 256,
        image_path: URL.createObjectURL(f),
      })),
      status: 'active',
    };

    setPois((prev) => [newPoi, ...prev]);
    setShowUpload(false);
  };

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-display font-medium text-intel-dark">Person of Interest Registry</h2>
          <p className="text-sm text-intel-gray mt-1">{pois.length} enrolled POI{pois.length !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => setShowUpload(true)}
          className="px-5 py-2.5 text-sm font-medium text-white bg-intel-blue rounded-lg hover:bg-intel-blue-dark transition-colors shadow-sm"
        >
          + Enroll POI
        </button>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
        {pois.map((poi) => (
          <POICard key={poi.poi_id} poi={poi} onDelete={handleDelete} onViewDetails={setDetailPoi} onImageClick={setPreviewImage} />
        ))}
      </div>

      {pois.length === 0 && (
        <div className="text-center py-20 text-intel-gray">
          <p className="text-lg">No POIs enrolled yet</p>
          <p className="text-sm mt-1">Click "Enroll POI" to get started</p>
        </div>
      )}

      {/* Modals */}
      {showUpload && <UploadModal onClose={() => setShowUpload(false)} onSave={handleSave} />}
      {detailPoi && <POIDetailModal poi={detailPoi} onClose={() => setDetailPoi(null)} onImageClick={setPreviewImage} />}
      {previewImage && <ImagePreviewModal imageUrl={previewImage} onClose={() => setPreviewImage(null)} />}
    </div>
  );
};

export default POIManagement;
