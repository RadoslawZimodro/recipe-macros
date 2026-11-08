import type { InputHTMLAttributes } from 'react'
import { Input } from './Input'

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: string
}

/** Label + input + optional hint. The label is the accessible name; the hint is linked via aria-describedby. */
export function Field({ label, hint, id, ...input }: FieldProps) {
  const fieldId = id ?? `field-${label}`
  const hintId = hint ? `${fieldId}-hint` : undefined
  return (
    <div className="space-y-1">
      <label htmlFor={fieldId} className="block text-small font-medium text-ink-2">
        {label}
      </label>
      <Input id={fieldId} aria-describedby={hintId} {...input} />
      {hint && (
        <p id={hintId} className="text-caption text-ink-3">
          {hint}
        </p>
      )}
    </div>
  )
}
