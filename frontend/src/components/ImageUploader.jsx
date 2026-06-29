import { useCallback, useRef, useState } from "react";
import axios from "axios";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { toast } from "sonner";
import { UploadCloud, X, Image as ImageIcon, Loader2 } from "lucide-react";
import { ACCEPT_IMG, MAX_IMG_BYTES, MAX_IMG_COUNT, imgUrl } from "@/lib/images";

const sanitizeName = (name) => {
  const base = (name || "image").split(/[\\/]/).pop().normalize("NFKD");
  return base.replace(/[^a-zA-Z0-9._-]+/g, "_").slice(0, 80) || "image";
};

const validate = (file) => {
  if (!ACCEPT_IMG.includes(file.type)) return `${file.name}: unsupported type (JPG, PNG, WEBP only)`;
  if (file.size > MAX_IMG_BYTES) return `${file.name}: exceeds 10 MB limit`;
  return null;
};

/**
 * ImageUploader — drag-and-drop multi-image uploader with progress + preview.
 * Props:
 *   value:    array of image refs already attached ({secure_url, public_id, width, height} or legacy string)
 *   onChange: (next: array) => void  — called whenever the list changes
 *   max:      maximum images (default 10)
 */
export default function ImageUploader({ value = [], onChange, max = MAX_IMG_COUNT }) {
  const [uploads, setUploads] = useState([]); // [{ id, name, progress, controller }]
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);

  const remaining = Math.max(0, max - value.length - uploads.length);

  const uploadOne = useCallback(async (file) => {
    const uid = `u_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const controller = new AbortController();
    setUploads((u) => [...u, { id: uid, name: file.name, progress: 0, controller }]);
    try {
      const { data: sig } = await api.get("/cloudinary/signature");
      const fd = new FormData();
      fd.append("file", file, sanitizeName(file.name));
      fd.append("api_key", sig.api_key);
      fd.append("timestamp", sig.timestamp);
      fd.append("signature", sig.signature);
      fd.append("folder", sig.folder);
      const cloudUrl = `https://api.cloudinary.com/v1_1/${sig.cloud_name}/image/upload`;
      const { data } = await axios.post(cloudUrl, fd, {
        signal: controller.signal,
        onUploadProgress: (evt) => {
          const pct = evt.total ? Math.round((evt.loaded / evt.total) * 100) : 0;
          setUploads((u) => u.map((x) => x.id === uid ? { ...x, progress: pct } : x));
        },
      });
      const ref = {
        secure_url: data.secure_url,
        public_id: data.public_id,
        width: data.width,
        height: data.height,
      };
      // Functional updater — safe under concurrent uploads (avoids stale-closure race).
      onChange((prev) => [...(Array.isArray(prev) ? prev : []), ref]);
    } catch (err) {
      if (axios.isCancel(err)) {
        toast.message(`Cancelled ${file.name}`);
      } else {
        toast.error(`${file.name}: ${err.response?.data?.error?.message || err.message || "upload failed"}`);
      }
    } finally {
      setUploads((u) => u.filter((x) => x.id !== uid));
    }
  }, [onChange]);

  const accept = useCallback((files) => {
    const list = Array.from(files || []);
    if (list.length === 0) return;
    if (remaining <= 0) { toast.error(`Max ${max} images`); return; }
    const slice = list.slice(0, remaining);
    if (list.length > remaining) toast.warning(`Only ${remaining} more allowed; ignoring extras`);
    for (const f of slice) {
      const err = validate(f);
      if (err) { toast.error(err); continue; }
      uploadOne(f);
    }
  }, [remaining, max, uploadOne]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    accept(e.dataTransfer.files);
  };

  const removeAt = async (idx) => {
    const img = value[idx];
    onChange((prev) => (prev || []).filter((_, i) => i !== idx));
    if (img && typeof img === "object" && img.public_id) {
      try { await api.delete("/cloudinary/image", { data: { public_id: img.public_id } }); }
      catch { /* best-effort; image already detached client-side */ }
    }
  };

  const cancelUpload = (uid) => {
    const u = uploads.find((x) => x.id === uid);
    u?.controller?.abort();
  };

  return (
    <div className="space-y-3" data-testid="image-uploader">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-colors
          ${dragOver ? "border-primary bg-primary/5" : "border-border hover:border-primary/60 hover:bg-muted/30"}`}
        data-testid="image-dropzone"
      >
        <UploadCloud className="mx-auto text-muted-foreground mb-2" size={28} />
        <div className="text-sm font-medium">Drag & drop, or click to upload</div>
        <div className="text-xs text-muted-foreground mt-1">JPG · PNG · WEBP · up to 10 MB · max {max} images</div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_IMG.join(",")}
          multiple
          className="hidden"
          data-testid="image-input"
          onChange={(e) => { accept(e.target.files); e.target.value = ""; }}
        />
      </div>

      {(value.length > 0 || uploads.length > 0) && (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {value.map((img, i) => (
            <div key={(typeof img === "object" ? img.public_id : img) || i}
                 data-testid={`image-tile-${i}`}
                 className="relative aspect-square bg-muted rounded-xl overflow-hidden group">
              <img src={imgUrl(img)} alt="" className="w-full h-full object-cover" />
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); removeAt(i); }}
                data-testid={`image-remove-${i}`}
                className="absolute top-1 right-1 bg-black/60 hover:bg-destructive text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label="Remove image"
              >
                <X size={14} />
              </button>
            </div>
          ))}
          {uploads.map((u) => (
            <div key={u.id} data-testid={`image-progress-${u.id}`}
                 className="relative aspect-square bg-muted rounded-xl overflow-hidden flex flex-col items-center justify-center p-3 gap-2">
              <Loader2 className="text-primary animate-spin" size={22} />
              <div className="text-[10px] text-center truncate max-w-full">{u.name}</div>
              <Progress value={u.progress} className="h-1.5 w-full" />
              <Button type="button" size="sm" variant="ghost"
                className="absolute top-1 right-1 h-6 w-6 p-0"
                onClick={() => cancelUpload(u.id)} aria-label="Cancel upload">
                <X size={12} />
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="text-xs text-muted-foreground flex items-center gap-1.5">
        <ImageIcon size={12} /> {value.length} / {max} images
      </div>
    </div>
  );
}
