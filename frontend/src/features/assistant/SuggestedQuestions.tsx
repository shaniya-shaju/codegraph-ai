interface SuggestedQuestionsProps {
  onSelect: (question: string) => void
}

const QUESTIONS = [
  'Where is user authentication implemented?',
  'Explain AuthService.login in simple terms.',
  'Which functions call AuthService.login?',
  'How does POST /login reach the repository layer?',
  'What could be affected if AuthService.login changes?',
]

export function SuggestedQuestions({ onSelect }: SuggestedQuestionsProps) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold tracking-wider uppercase" style={{ color: 'var(--text-muted)' }}>
        Suggested Prompts
      </p>
      <div className="flex flex-col gap-2">
        {QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSelect(q)}
            className="w-full rounded-lg border p-3.5 text-left text-sm font-medium transition-all hover:translate-x-1 shadow-xs"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-subtle)',
              color: 'var(--text-primary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bg-card)'
              e.currentTarget.style.borderColor = 'var(--accent)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--bg-surface)'
              e.currentTarget.style.borderColor = 'var(--border-subtle)'
            }}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}