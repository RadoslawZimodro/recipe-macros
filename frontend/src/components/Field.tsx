import type { InputHTMLAttributes } from 'react'

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: string
}

export function Field({ label, hint, id, ...input }: FieldProps) {
  const fieldId = id ?? `field-${label}`
  return (
    <div className="space-y-1">
      <label htmlFor={fieldId} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={fieldId}
        className="block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-emerald-600 focus:outline-none focus:ring-2 focus:ring-emerald-600/30 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
        {...input}
      />
      {hint && <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  )
}

export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p
      role="alert"
      className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
    >
      {message}
    </p>
  )
}
