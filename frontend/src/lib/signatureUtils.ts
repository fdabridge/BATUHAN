/**
 * Process a signature image file:
 * - Scales it down to max 600 × 200 px
 * - Composites it onto a white canvas (handles semi-transparent JPEGs)
 * - Removes near-white pixels (R,G,B > 220) → transparent background
 * - Returns a PNG data URL suitable for stamping on documents
 */
export function removeWhiteBackground(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = reject
    reader.onload = (e) => {
      const src = e.target?.result as string
      const img = new Image()
      img.onerror = reject
      img.onload = () => {
        const MAX_W = 600
        const MAX_H = 200
        let w = img.naturalWidth
        let h = img.naturalHeight
        if (w > MAX_W) { h = Math.round(h * MAX_W / w); w = MAX_W }
        if (h > MAX_H) { w = Math.round(w * MAX_H / h); h = MAX_H }

        const canvas = document.createElement('canvas')
        canvas.width  = w
        canvas.height = h
        const ctx = canvas.getContext('2d')!

        // White fill first so JPEG alpha-composites correctly
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, w, h)
        ctx.drawImage(img, 0, 0, w, h)

        const imageData = ctx.getImageData(0, 0, w, h)
        const d = imageData.data
        for (let i = 0; i < d.length; i += 4) {
          if (d[i] > 220 && d[i + 1] > 220 && d[i + 2] > 220) {
            d[i + 3] = 0   // make near-white pixels transparent
          }
        }
        ctx.clearRect(0, 0, w, h)
        ctx.putImageData(imageData, 0, 0)

        resolve(canvas.toDataURL('image/png'))
      }
      img.src = src
    }
    reader.readAsDataURL(file)
  })
}

/** Frontend size guard — must stay consistent with backend _MAX_DATA_LEN */
export const MAX_SIGNATURE_FILE_BYTES = 10 * 1024 * 1024  // 10 MB raw before base64 (backend is ~1.5 MB base64)
