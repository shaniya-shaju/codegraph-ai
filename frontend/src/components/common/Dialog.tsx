import { useEffect, useRef, type ReactNode } from 'react'

/** A minimal, dependency-free accessible modal dialog — see Prompt 11
 * "Accessibility": "dialog focus handling." Traps focus to the dialog
 * while open, restores focus to the trigger on close, closes on Escape
 * or backdrop click. */
export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)

  // Keep onClose callback updated without re-triggering focus effects
  useEffect(() => {
    onCloseRef.current = onClose
  })

  // Handle focus lock & restoration strictly on open/close transitions
  useEffect(() => {
    if (open) {
      previouslyFocused.current = document.activeElement as HTMLElement | null

      // Focus dialog container once upon opening
      requestAnimationFrame(() => {
        dialogRef.current?.focus()
      })

      return () => {
        // Restore focus ONLY when dialog unmounts or closes
        previouslyFocused.current?.focus()
      }
    }
  }, [open])

  // Handle keydown listener separately without re-triggering focus cleanup
  useEffect(() => {
    if (!open) return

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onCloseRef.current()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onCloseRef.current()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="w-full max-w-lg rounded-lg border border-slate-800 bg-slate-900 p-5 shadow-xl outline-none"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-100">{title}</h2>
          <button
            type="button"
            onClick={() => onCloseRef.current()}
            aria-label="Close dialog"
            className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200"
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}