import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ImageOff, Video } from "lucide-react"
import { fetchMediaObjectUrl } from "@/lib/api"
import type { Media } from "@/lib/types"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

function isVideo(media: Media): boolean {
  if (media.kind) return media.kind.toLowerCase().startsWith("video")
  return /\.(mp4|webm|mov|m4v|ogg)(\?|$)/i.test(media.url)
}

/**
 * <img src> cannot carry an Authorization header, so the file is fetched as a
 * blob with the bearer token and shown through an object URL.
 */
export function MediaThumb({ media, className }: { media: Media; className?: string }) {
  const { t } = useTranslation()
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const video = isVideo(media)

  useEffect(() => {
    const ac = new AbortController()
    let objectUrl: string | null = null
    setSrc(null)
    setFailed(false)
    // Only known photo and video types come back as a URL; anything else (an old SVG upload, say)
    // fails here and shows the "could not load" tile instead of being rendered or opened.
    fetchMediaObjectUrl(media.url, ac.signal)
      .then((u) => {
        objectUrl = u
        setSrc(u)
      })
      .catch(() => {
        if (!ac.signal.aborted) setFailed(true)
      })
    return () => {
      ac.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [media.url])

  const box = cn("relative aspect-square overflow-hidden rounded-lg bg-muted ring-1 ring-foreground/10", className)

  if (failed) {
    return (
      <div className={cn(box, "flex items-center justify-center text-muted-foreground")} title={t("media.failed")}>
        <ImageOff className="size-5" />
      </div>
    )
  }
  if (!src) return <Skeleton className={box} />

  if (video) {
    return (
      <div className={box}>
        <video src={src} controls playsInline preload="metadata" className="size-full object-cover" />
        <Video className="pointer-events-none absolute top-1 left-1 size-4 text-white drop-shadow" />
      </div>
    )
  }
  return (
    <a href={src} target="_blank" rel="noreferrer" className={box}>
      <img src={src} alt={t("media.attachment")} className="size-full object-cover" />
    </a>
  )
}
