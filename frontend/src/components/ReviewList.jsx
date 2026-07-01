import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import StarRating from "@/components/StarRating";
import { EditReviewButton } from "@/components/ReviewForm";
import { imgUrl } from "@/lib/images";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { BadgeCheck, Flag, MessageSquareReply, ShieldAlert, EyeOff, Eye, Trash2 } from "lucide-react";

/**
 * ReviewList — list reviews with verified-purchase badge, optional inline
 * farmer reply, report + admin moderation controls.
 *
 * Props:
 *   reviews:    array of review docs
 *   currentUser: { user_id, role } from useAuth (optional fallback)
 *   role:       "buyer" | "farmer" | "admin" — drives which controls render
 *   onChange:   reload callback
 *   showProductTitle: bool — include product label (for farmer view)
 */
export default function ReviewList({ reviews, role = "buyer", onChange, showProductTitle = false }) {
  if (!reviews || reviews.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center" data-testid="reviews-empty">
        No reviews yet.
      </p>
    );
  }
  return (
    <div className="space-y-4" data-testid="review-list">
      {reviews.map((r) => (
        <ReviewItem key={r.review_id} review={r}
          role={role} onChange={onChange} showProductTitle={showProductTitle} />
      ))}
    </div>
  );
}

function ReviewItem({ review, role, onChange, showProductTitle }) {
  const { user } = useAuth();
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [busy, setBusy] = useState(false);

  const submitReply = async () => {
    if (!replyText.trim()) return;
    setBusy(true);
    try {
      await api.post(`/reviews/${review.review_id}/reply`, { body: replyText });
      toast.success("Reply posted");
      setReplyOpen(false); setReplyText("");
      onChange?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not reply");
    } finally { setBusy(false); }
  };

  const report = async () => {
    const reason = window.prompt("Why are you reporting this review?", "inappropriate content");
    if (reason == null) return;
    try {
      await api.post(`/reviews/${review.review_id}/report`, { reason });
      toast.success("Reported — admins will review it");
      onChange?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Could not report");
    }
  };

  const moderate = async (action) => {
    if (action === "delete" && !window.confirm("Delete this review permanently?")) return;
    setBusy(true);
    try {
      await api.post(`/admin/reviews/${review.review_id}/moderate`, { action });
      toast.success(`Review ${action}d`);
      onChange?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Moderation failed");
    } finally { setBusy(false); }
  };

  const isOwner = user?.user_id === review.buyer_id;
  const isFarmerOfReview = user?.user_id === review.farmer_id;

  return (
    <div
      data-testid={`review-${review.review_id}`}
      className={`border-2 rounded-2xl p-4 ${
        review.status === "hidden" ? "border-dashed border-muted-foreground/40 bg-muted/30"
        : review.status === "reported" ? "border-amber-300 bg-amber-50/50 dark:bg-amber-950/10"
        : "border-border bg-card"
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-full bg-primary text-primary-foreground flex items-center justify-center font-semibold shrink-0">
          {review.buyer_name?.[0]?.toUpperCase() || "U"}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold">{review.buyer_name}</span>
            {review.verified_purchase && (
              <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide bg-primary/10 text-primary px-2 py-0.5 rounded-full font-semibold"
                data-testid={`verified-${review.review_id}`}>
                <BadgeCheck size={10} /> Verified Purchase
              </span>
            )}
            {review.status === "hidden" && <span className="text-xs text-muted-foreground">(hidden)</span>}
            {review.status === "reported" && (
              <span className="text-xs text-amber-600 inline-flex items-center gap-1">
                <ShieldAlert size={12} /> reported
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <StarRating value={review.rating} size={14} testid={`row-star-${review.review_id}`} />
            <span className="text-xs text-muted-foreground">
              {review.created_at ? new Date(review.created_at).toLocaleDateString() : ""}
            </span>
          </div>
          {showProductTitle && review.product_title && (
            <div className="text-xs text-muted-foreground mt-1">on <b>{review.product_title}</b></div>
          )}
          {review.title && <div className="font-medium mt-2">{review.title}</div>}
          <p className="text-sm mt-1 whitespace-pre-line break-words">{review.body}</p>

          {review.images?.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3">
              {review.images.map((img, i) => (
                <a key={i} href={imgUrl(img)} target="_blank" rel="noreferrer"
                  className="block w-20 h-20 rounded-xl overflow-hidden border border-border">
                  <img src={imgUrl(img)} alt="" className="w-full h-full object-cover" />
                </a>
              ))}
            </div>
          )}

          {review.reply && (
            <div className="mt-3 ml-1 pl-3 border-l-2 border-primary/60 bg-primary/5 rounded-r-xl py-2 px-3"
              data-testid={`reply-${review.review_id}`}>
              <div className="text-[11px] uppercase tracking-wide text-primary font-semibold">Farmer reply</div>
              <p className="text-sm whitespace-pre-line mt-0.5">{review.reply.body}</p>
            </div>
          )}

          {role === "farmer" && isFarmerOfReview && !review.reply && (
            replyOpen ? (
              <div className="mt-3 space-y-2">
                <Textarea data-testid={`reply-input-${review.review_id}`}
                  value={replyText} onChange={(e) => setReplyText(e.target.value)}
                  placeholder="Thank the buyer or clarify any concerns…"
                  rows={3} maxLength={1000} className="rounded-xl" />
                <div className="flex gap-2">
                  <Button size="sm" onClick={submitReply} disabled={busy}
                    data-testid={`reply-submit-${review.review_id}`}>Post reply</Button>
                  <Button size="sm" variant="ghost" onClick={() => setReplyOpen(false)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <Button size="sm" variant="outline" className="mt-3 rounded-xl"
                onClick={() => setReplyOpen(true)} data-testid={`reply-btn-${review.review_id}`}>
                <MessageSquareReply size={14} className="mr-1" /> Reply
              </Button>
            )
          )}

          <div className="flex gap-1 mt-3 flex-wrap">
            {isOwner && <EditReviewButton review={review} onSaved={onChange} />}
            {user && !isOwner && review.status === "published" && (
              <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground"
                onClick={report} data-testid={`report-${review.review_id}`}>
                <Flag size={12} className="mr-1" /> Report
              </Button>
            )}
            {role === "admin" && (
              <div className="flex gap-1">
                {review.status !== "published" && (
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                    disabled={busy} onClick={() => moderate("publish")}
                    data-testid={`mod-publish-${review.review_id}`}>
                    <Eye size={12} className="mr-1" /> Publish
                  </Button>
                )}
                {review.status !== "hidden" && (
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs"
                    disabled={busy} onClick={() => moderate("hide")}
                    data-testid={`mod-hide-${review.review_id}`}>
                    <EyeOff size={12} className="mr-1" /> Hide
                  </Button>
                )}
                <Button size="sm" variant="destructive" className="h-7 px-2 text-xs"
                  disabled={busy} onClick={() => moderate("delete")}
                  data-testid={`mod-delete-${review.review_id}`}>
                  <Trash2 size={12} className="mr-1" /> Delete
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
