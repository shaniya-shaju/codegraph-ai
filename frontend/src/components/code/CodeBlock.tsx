import Prism from 'prismjs'
import 'prismjs/components/prism-python'
import { useEffect, useMemo, useRef, useState } from 'react'

/** A reusable, read-only source viewer — see Prompt 11 "Code
 * Formatting": line numbers, highlighted citation lines, horizontal
 * scrolling, copy button. Uses Prism directly (not the heavier
 * react-syntax-highlighter) since only Python is ever shown. */
export function CodeBlock({
  code,
  startLine = 1,
  highlightStart,
  highlightEnd,
}: {
  code: string
  startLine?: number
  highlightStart?: number | null
  highlightEnd?: number | null
}) {
  const [copied, setCopied] = useState(false)
  const highlighted = useMemo(() => Prism.highlight(code, Prism.languages.python, 'python'), [code])
  const lines = useMemo(() => highlighted.split('\n'), [highlighted])
  const highlightedLineRef = useRef<HTMLTableRowElement | null>(null)

  useEffect(() => {
    highlightedLineRef.current?.scrollIntoView({ block: 'center' })
  }, [code, highlightStart])

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard API unavailable (e.g. insecure context) — no-op.
    }
  }

  return (
    <div className="relative rounded border border-slate-800 bg-slate-950">
      <button
        type="button"
        onClick={handleCopy}
        className="absolute right-2 top-2 z-10 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse font-mono text-xs leading-6">
          <tbody>
            {lines.map((lineHtml, index) => {
              const lineNumber = startLine + index
              const isHighlighted =
                highlightStart != null &&
                lineNumber >= highlightStart &&
                lineNumber <= (highlightEnd ?? highlightStart)
              return (
                <tr
                  key={lineNumber}
                  ref={isHighlighted ? highlightedLineRef : undefined}
                  className={isHighlighted ? 'bg-sky-500/10' : undefined}
                >
                  <td
                    className={`select-none whitespace-nowrap px-3 text-right text-slate-600 ${
                      isHighlighted ? 'border-l-2 border-sky-500' : 'border-l-2 border-transparent'
                    }`}
                  >
                    {lineNumber}
                  </td>
                  {/* Prism-generated markup, not user input. */}
                  <td className="w-full pr-4" dangerouslySetInnerHTML={{ __html: lineHtml || ' ' }} />
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
