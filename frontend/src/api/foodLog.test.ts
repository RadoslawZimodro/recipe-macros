import { describe, expect, it } from 'vitest'
import { addDays, loggedAtFor, todayInPoland } from './foodLog'

const warsawDay = (instant: string) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw' }).format(new Date(instant))

describe('loggedAtFor', () => {
  // Winter, summer, and the two DST change days (2026-03-29 and 2026-10-25).
  it.each(['2026-01-15', '2026-07-15', '2026-03-29', '2026-10-25'])(
    'stays on the same Warsaw calendar day for %s',
    (day) => {
      const loggedAt = loggedAtFor(day)!
      expect(warsawDay(loggedAt)).toBe(day)
      expect(new Date(loggedAt).toISOString()).toBe(`${day}T11:00:00.000Z`)
    },
  )

  it('returns undefined for today', () => {
    expect(loggedAtFor(todayInPoland())).toBeUndefined()
  })
})

describe('addDays', () => {
  it('crosses the DST change days without skipping or repeating a date', () => {
    expect(addDays('2026-03-28', 1)).toBe('2026-03-29')
    expect(addDays('2026-03-29', 1)).toBe('2026-03-30')
    expect(addDays('2026-10-24', 1)).toBe('2026-10-25')
    expect(addDays('2026-10-25', 1)).toBe('2026-10-26')
    expect(addDays('2026-10-26', -1)).toBe('2026-10-25')
  })
})
