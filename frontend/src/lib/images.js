/**
 * Image URL helpers. Products store images as objects: { secure_url, public_id, width, height }.
 * Legacy seed data may still hold plain string URLs — both are accepted.
 *
 * `imgUrl()` returns the renderable URL and, for Cloudinary assets, injects
 * `f_auto,q_auto` at delivery time so we never need to re-upload to gain
 * format/quality optimisation.
 */
export const imgUrl = (img) => {
  const raw = typeof img === "string" ? img : (img?.secure_url || "");
  if (!raw) return "";
  if (raw.includes("/res.cloudinary.com/") && raw.includes("/upload/") && !/\/upload\/[a-z]_/.test(raw)) {
    return raw.replace("/upload/", "/upload/f_auto,q_auto/");
  }
  return raw;
};

/** Accepted file types for product image uploads. */
export const ACCEPT_IMG = ["image/jpeg", "image/jpg", "image/png", "image/webp"];
export const MAX_IMG_BYTES = 10 * 1024 * 1024;
export const MAX_IMG_COUNT = 10;
