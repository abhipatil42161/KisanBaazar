import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import StarRating from "@/components/StarRating";
import ImageUploader from "@/components/ImageUploader";
import { Pencil } from "lucide-react";

/**
 * ReviewForm — modal dialog to create or edit a review.
 * Props:
 *   trigger:        ReactNode used as DialogTrigger
 *   eligible:       { order_id, product_id, product_title } when creating, else null
 *   existing:       existing review doc when editing, else null
 *   onSaved:        callback after success (refresh list)
 */
export default function ReviewForm({ trigger, eligible = null, existing = null, onSaved }) {
  const editing = !!existing;
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState(existing?.rating || 0);
  const [title, setTitle] = useState(existing?.title || "");
  const [body, setBody] = useState(existing?.body || "");
  const [images, setImages] = useState(existing?.images || []);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setRating(existing?.rating || 0);
    setTitle(existing?.title || "");
    setBody(existing?.body || "");
    setImages(existing?.images || []);
  };

  const submit = async () => {
    if (rating < 1 || rating > 5) { toast.error("Please pick a star rating"); return; }
    if (!body.trim()) { toast.error("Please write your review"); return; }
    setBusy(true);
    try {
      if (editing) {
        await api.put(`/reviews/${existing.review_id}`, { rating, title, body, images });
        toast.success("Review updated");
      } else {
        await api.post("/reviews", {
          order_id: eligible.order_id, product_id: eligible.product_id,
          rating, title, body, images,
        });
        toast.success("Thanks for your review!");
      }
      setOpen(false);
      onSaved?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not save review");
    } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) reset(); }}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-lg" data-testid="review-form-dialog">
        <DialogHeader>
          <DialogTitle>{editing ? "Edit your review" : `Review · ${eligible?.product_title || ""}`}</DialogTitle>
          <DialogDescription>
            Your review is tagged as a <b>Verified Purchase</b>. Be honest and helpful.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium block mb-1">Your rating</label>
            <StarRating value={rating} onChange={setRating} size={28} testid="review-form-star" />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">Title (optional)</label>
            <Input data-testid="review-form-title" maxLength={120}
              value={title} onChange={(e) => setTitle(e.target.value)}
              placeholder="Sum it up in a few words" className="h-11 rounded-xl" />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">Your review</label>
            <Textarea data-testid="review-form-body" maxLength={2000} rows={5}
              value={body} onChange={(e) => setBody(e.target.value)}
              placeholder="Quality, packaging, freshness, delivery experience…"
              className="rounded-xl" />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">Photos (optional)</label>
            <ImageUploader value={images} onChange={setImages} max={5} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} data-testid="review-form-cancel">Cancel</Button>
          <Button onClick={submit} disabled={busy} data-testid="review-form-submit"
            className="bg-primary hover:bg-primary/90 rounded-xl">
            {busy ? "Saving…" : editing ? "Save changes" : "Submit review"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export const EditReviewButton = ({ review, onSaved }) => (
  <ReviewForm existing={review} onSaved={onSaved}
    trigger={<Button size="sm" variant="ghost" className="h-7 px-2 text-xs"
      data-testid={`edit-review-${review.review_id}`}>
      <Pencil size={12} className="mr-1" /> Edit
    </Button>} />
);
