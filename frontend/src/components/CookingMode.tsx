import { useEffect, useId, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { API_URL } from '../api/client'
import type { IngredientLine, RecipeStep } from '../api/recipes'
import { Button } from './ui/Button'
import { cx } from './ui/cx'

interface CookingModeProps {
  open: boolean
  onClose: () => void
  title: string
  steps: RecipeStep[]
  ingredients: IngredientLine[]
  /** Element that opened the dialog; focus returns to it on close. */
  opener: RefObject<HTMLElement | null>
}

// image_url is relative to the API, which is the same site as the app (host without port),
// so the browser sends the session cookie with the <img> request.
const imageSrc = (url: string) => `${API_URL}${url}`

// Only our own relative image path is rendered: anything else (another host via concatenation,
// "//host", javascript:, or a missing field before the API sends it) shows the step without a photo.
const IMAGE_PATH = /^\/recipes\/\d+\/steps\/\d+\/image$/
const safeImage = (url: string | null | undefined) => (url && IMAGE_PATH.test(url) ? url : null)

/**
 * Step-by-step view in a native modal <dialog>: the browser provides the focus trap and the
 * inert background. Escape, scroll lock and focus return are done here so they behave the same
 * everywhere (and in tests).
 */
export function CookingMode({ open, onClose, title, steps, ingredients, opener }: CookingModeProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      document.body.style.overflow = 'hidden' // the native modal does not lock page scrolling
    }
    if (!open && dialog.open) dialog.close()
    return () => {
      document.body.style.overflow = ''
    }
  }, [open])

  function close() {
    onClose()
    opener.current?.focus()
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-modal="true"
      onCancel={(e) => {
        e.preventDefault() // we close through state, see close()
        close()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault()
          close()
        }
      }}
      onClick={(e) => {
        if (e.target === ref.current) close() // click on the backdrop, not on the content
      }}
      className="m-0 h-dvh max-h-none w-full max-w-none border-0 bg-surface p-0 text-ink backdrop:bg-canvas/80 sm:m-auto sm:h-auto sm:max-h-[90dvh] sm:max-w-3xl sm:rounded-lg sm:border sm:border-line"
    >
      {open && (
        <CookingBody titleId={titleId} title={title} steps={steps} ingredients={ingredients} onClose={close} />
      )}
    </dialog>
  )
}

function CookingBody({
  titleId,
  title,
  steps,
  ingredients,
  onClose,
}: {
  titleId: string
  title: string
  steps: RecipeStep[]
  ingredients: IngredientLine[]
  onClose: () => void
}) {
  const [index, setIndex] = useState(0)
  const [failed, setFailed] = useState<Set<string>>(new Set())
  const last = steps.length - 1
  const step = steps[index]
  const imageUrl = safeImage(step.image_url)
  const showImage = imageUrl !== null && !failed.has(imageUrl)

  // Warm the cache so the next photo is there when "Dalej" is pressed.
  useEffect(() => {
    const next = safeImage(steps[index + 1]?.image_url)
    if (next) new Image().src = imageSrc(next)
  }, [index, steps])

  const go = (i: number) => setIndex(Math.min(last, Math.max(0, i)))

  return (
    <div
      className="flex h-full max-h-[inherit] flex-col gap-4 overflow-y-auto p-4 sm:p-6"
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') go(index - 1)
        if (e.key === 'ArrowRight') go(index + 1)
      }}
    >
      <header className="flex items-start justify-between gap-4">
        <h2 id={titleId} className="text-h3">
          {title}
        </h2>
        <Button variant="ghost" onClick={onClose} aria-label="Zamknij tryb gotowania" className="shrink-0">
          Zamknij
        </Button>
      </header>

      <div className="space-y-2">
        <p className="text-small tabular-nums text-ink-2">
          Krok {index + 1} z {steps.length}
        </p>
        <div
          role="progressbar"
          aria-label="Postęp"
          aria-valuemin={1}
          aria-valuemax={steps.length}
          aria-valuenow={index + 1}
          className="h-1 overflow-hidden rounded-sm bg-inset"
        >
          <div
            className="h-full bg-accent transition-[width] duration-200 ease-soft motion-reduce:transition-none"
            style={{ width: `${((index + 1) / steps.length) * 100}%` }}
          />
        </div>
      </div>

      <div aria-live="polite" className="flex-1 space-y-4">
        {showImage && (
          <img
            key={imageUrl}
            src={imageSrc(imageUrl)}
            alt={`Zdjęcie do kroku ${index + 1}`}
            onError={() => setFailed((prev) => new Set(prev).add(imageUrl))}
            className="aspect-video max-h-[40dvh] w-full rounded-md border border-line bg-inset object-cover"
          />
        )}
        <p className="max-w-reading text-h3 leading-relaxed">{step.instruction}</p>
      </div>

      <details className="rounded-md border border-line bg-raised px-4 text-ink-2">
        <summary className="cursor-pointer rounded-sm py-3 font-medium text-ink">Składniki</summary>
        {ingredients.length === 0 ? (
          <p className="pb-3 text-small">Ten przepis nie ma składników.</p>
        ) : (
          <ul className="list-disc space-y-1 pb-3 pl-6">
            {ingredients.map((line) => (
              <li key={line.id}>{line.raw_text}</li>
            ))}
          </ul>
        )}
      </details>

      <nav aria-label="Kroki" className="flex flex-wrap gap-1">
        {steps.map((s, i) => (
          <button
            key={s.position}
            type="button"
            onClick={() => go(i)}
            aria-label={`Krok ${i + 1}`}
            aria-current={i === index ? 'step' : undefined}
            className={cx(
              'press h-10 min-w-10 rounded-sm text-small tabular-nums transition-colors duration-150',
              i === index ? 'bg-accent text-on-accent' : 'text-ink-2 hover:bg-raised hover:text-ink',
            )}
          >
            {i + 1}
          </button>
        ))}
      </nav>

      <div className="flex justify-between gap-2">
        <Button variant="secondary" onClick={() => go(index - 1)} disabled={index === 0}>
          Wstecz
        </Button>
        {index === last ? (
          <Button onClick={onClose}>Zakończ</Button>
        ) : (
          <Button onClick={() => go(index + 1)}>Dalej</Button>
        )}
      </div>
    </div>
  )
}
