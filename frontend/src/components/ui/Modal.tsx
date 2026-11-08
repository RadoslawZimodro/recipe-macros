import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'

interface ModalProps {
  open: boolean
  /** Called on Escape, backdrop click and when the dialog closes for any other reason. */
  onClose: () => void
  title: string
  children: ReactNode
}

/**
 * Native <dialog> opened with showModal(): the browser provides the focus trap, Escape
 * and returning focus to the element that opened it.
 */
export function Modal({ open, onClose, title, children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose() // click on the backdrop, not on the content
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-lg border border-line bg-raised p-6 text-ink backdrop:bg-canvas/80"
    >
      <div className="space-y-4">
        <h2 id={titleId} className="text-h3">
          {title}
        </h2>
        {children}
      </div>
    </dialog>
  )
}
